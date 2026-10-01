"""Exact caller-supplied Legal qualifier interpretations, never prose inference.

A declaration covers every original condition and exception in order. Conditions
are activation predicates; one condition may instead be an exact bounded duration.
Exceptions either waive activation, or exempt individual ticks of an explicitly
universal minimum-duration body. These choices are caller premises and do not
establish that the source law has the chosen meaning. Existing producers and
uninterpreted default targets are deliberately unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from . import native_qualified_lean as base
from . import native_family_lean_emitters as old
from ...ir_core.provenance import SourceRef

EVIDENCE_SCHEMA = "legal-qualifier-interpretation/v1"
PAYLOAD_SCHEMA = "legal-qualified-interpretation/v1"
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
require, string, digest = old.require, old.string, base.digest


def _guard():
    base._guard()
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
            "legal_qualifier_producer_changed")


def _evidence(value):
    base._closed(value, {"schema", "source_ref", "original_projection_id", "original_source_digest",
        "original_payload_sha256", "declaration_scope", "formulas"}, "legal_interpretation")
    require(value["schema"] == EVIDENCE_SCHEMA, "legal_interpretation_schema_required")
    base._source(value["source_ref"])
    base._text(value["original_projection_id"], "original_projection_id")
    base._sha(value["original_source_digest"]); base._sha(value["original_payload_sha256"])
    require(value["declaration_scope"] == "caller_supplied_interpretation_not_source_translation",
            "explicit_interpretation_scope_required")
    for index, row in enumerate(base._list(value["formulas"], "formula_interpretations")):
        require(type(row) is dict and type(row.get("formula_index")) is int and row["formula_index"] == index,
                "exhaustive_ordered_formula_interpretations_required")
        base._sha(row.get("original_formula_sha256"))


@dataclass(frozen=True, slots=True)
class LegalQualifierInterpretation:
    """Canonical immutable declaration bytes; decoded views are copies."""
    _bytes: bytes

    def __post_init__(self):
        require(type(self._bytes) is bytes and len(self._bytes) <= 262144,
                "bounded_legal_interpretation_bytes_required")
        value = json.loads(self._bytes)
        _evidence(value)
        require(base._wire(value) == self._bytes, "canonical_legal_interpretation_bytes_required")

    @classmethod
    def from_dict(cls, value):
        return cls(base._wire(value))

    def to_dict(self):
        return json.loads(self._bytes)

    @property
    def sha256(self):
        return hashlib.sha256(self._bytes).hexdigest()


def _expression(value, time, *, depth=0, budget=None):
    if budget is None:
        budget = [64]
    budget[0] -= 1
    require(depth <= 8 and budget[0] >= 0 and type(value) is dict,
            "bounded_typed_qualifier_expression_required")
    op = value.get("op")
    if op == "atom":
        base._closed(value, {"op", "predicate"}, "qualifier_atom")
        return "(" + base._predicate(value["predicate"]) + " " + time + ")"
    if op == "not":
        base._closed(value, {"op", "operand"}, "qualifier_negation")
        return "(¬ " + _expression(value["operand"], time, depth=depth + 1, budget=budget) + ")"
    require(op in {"all", "any"}, "unsupported_qualifier_expression_operator")
    base._closed(value, {"op", "operands"}, "qualifier_boolean")
    operands = base._list(value["operands"], "qualifier_operands", bound=16)
    require(len(operands) >= 2, "nontrivial_qualifier_boolean_required")
    join = " ∧ " if op == "all" else " ∨ "
    return "(" + join.join(_expression(child, time, depth=depth + 1, budget=budget) for child in operands) + ")"


def _bindings(native, bindings, *, label, indices, literal_bindings):
    require(type(bindings) is list and len(bindings) == len(indices), "exhaustive_" + label + "_bindings_required")
    expressions = []
    for index, binding in zip(indices, bindings):
        base._closed(binding, {"source_index", "source_text", "expression"}, label + "_binding")
        require(type(binding["source_index"]) is int and binding["source_index"] == index and
                binding["source_text"] == native[index], "ordered_" + label + "_binding_differs")
        expression = binding["expression"]
        _expression(expression, "t")
        literal = binding["source_text"]
        if literal in literal_bindings:
            require(literal_bindings[literal] == expression, "same_qualifier_literal_has_conflicting_interpretations")
        else:
            literal_bindings[literal] = expression
        expressions.append(expression)
    return expressions


def _formula(row, declaration, family, literal_bindings):
    base._closed(row, {"conditions", "exceptions", "formula_id", "metadata", "operator", "predicate", "provenance"}, "ModalIR_formula")
    base._text(row["formula_id"], "formula_id")
    require(row["metadata"] == {}, "uninterpreted_ModalIR_metadata")
    base._closed(row["provenance"], {"source_id", "start_char", "end_char", "citation"}, "ModalIR_provenance")
    base._closed(row["operator"], {"family", "system", "symbol", "label"}, "ModalIR_operator")
    base._closed(row["predicate"], {"name", "arguments", "role"}, "ModalIR_predicate")
    require(row["predicate"]["role"] in (None, "clause"), "unsupported_ModalIR_predicate_role")
    atom = base._predicate({key: row["predicate"][key] for key in ("name", "arguments")})
    op = row["operator"]
    legal_ops = {"O": "obligation", "P": "permission", "F": "prohibition"}
    temporal_ops = {"F": "eventually", "G": "always"}
    require(op["family"] == family and (
        family == "deontic" and op["system"] == "D" and legal_ops.get(op["symbol"]) == op["label"] or
        family == "temporal" and op["system"] == "LTL" and temporal_ops.get(op["symbol"]) == op["label"]),
        "unsupported_qualified_native_operator")
    base._closed(declaration, {"formula_index", "original_formula_sha256", "kind", "activation_scope",
        "conditions", "temporal", "exception_scope", "exceptions"}, "legal_qualifier_formula")
    require(declaration["kind"] == "activation_guarded_legal_rule" and
            declaration["activation_scope"] == "all_conditions_at_evaluation_origin",
            "explicit_activation_scope_required")
    conditions = base._list(row["conditions"], "native_conditions", empty=True, bound=16)
    exceptions = base._list(row["exceptions"], "native_exceptions", empty=True, bound=8)
    for literal in conditions + exceptions:
        base._text(literal, "qualifier_literal")
    temporal, quantity, unit, kind, temporal_index = declaration["temporal"], None, None, None, None
    if temporal is not None:
        base._closed(temporal, {"source_index", "source_text", "temporal_kind", "quantity", "unit", "time_domain",
            "origin", "lower_inclusive", "upper_inclusive"}, "temporal_interpretation")
        require(temporal["time_domain"] == "discrete_nat" and temporal["origin"] == "caller_supplied_evaluation_time"
                and temporal["lower_inclusive"] is True and temporal["upper_inclusive"] is True,
                "explicit_discrete_closed_interval_required")
        quantity, unit, kind = temporal["quantity"], temporal["unit"], temporal["temporal_kind"]
        require(type(quantity) is int and 1 <= quantity <= 1000000, "positive_bounded_temporal_quantity_required")
        require(unit in {"day", "hour"} and kind in {"within_duration", "minimum_duration"},
                "supported_explicit_kind_and_unit_required")
        temporal_index = temporal["source_index"]
        require(type(temporal_index) is int and 0 <= temporal_index < len(conditions), "exact_temporal_source_index_required")
        duration = str(quantity) + " " + unit + ("s" if quantity != 1 else "")
        literal = ("within " if kind == "within_duration" else "for at least ") + duration
        require(temporal["source_text"] == literal and conditions[temporal_index] == literal,
                "temporal_literal_kind_quantity_unit_differs")
        require(family != "temporal" or op["symbol"] == ("F" if kind == "within_duration" else "G"),
                "temporal_operator_disagrees_with_explicit_qualification")
    require(family != "temporal" or temporal is not None, "temporal_family_requires_explicit_interval")
    require(all(index == temporal_index or re.fullmatch(r"(?:within|for at least) [0-9]+ (?:days?|hours?)", literal) is None
                for index, literal in enumerate(conditions)), "duration_literal_cannot_be_an_activation_atom")
    activation = _bindings(conditions, declaration["conditions"], label="condition",
        indices=[index for index in range(len(conditions)) if index != temporal_index], literal_bindings=literal_bindings)
    exemptions = _bindings(exceptions, declaration["exceptions"], label="exception",
        indices=list(range(len(exceptions))), literal_bindings=literal_bindings)
    scope = declaration["exception_scope"]
    require(scope in {"activation_time_waiver", "per_tick_exemption"}, "unsupported_exception_scope")
    require(scope != "per_tick_exemption" or kind == "minimum_duration" and bool(exemptions),
            "per_tick_exemption_requires_minimum_duration_and_exceptions")
    def exceptions_at(time):
        return "(" + " ∨ ".join(_expression(e, time) for e in exemptions) + ")"
    tick = atom + " u"
    if scope == "per_tick_exemption":
        tick = "(¬ " + exceptions_at("u") + " → " + tick + ")"
    if kind == "within_duration":
        body = "(fun origin => ∃ u, origin ≤ u ∧ u ≤ origin + " + str(quantity) + " ∧ " + tick + ")"
    elif kind == "minimum_duration":
        body = "(fun origin => ∀ u, origin ≤ u → u ≤ origin + " + str(quantity) + " → " + tick + ")"
    else:
        body = atom
    if family == "deontic":
        annotation = "explicit-clock:" + (unit or "instantaneous")
        body = "(i.modal " + string("deontic:" + op["symbol"]) + " [] (some " + string(annotation) + ") " + body + ")"
    guards = [_expression(e, "t") for e in activation]
    if scope == "activation_time_waiver" and exemptions:
        guards.append("(¬ " + exceptions_at("t") + ")")
    if guards:
        body = "(fun t => (" + " ∧ ".join(guards) + ") → " + body + " t)"
    return body, ["activation_all", scope, kind or "instantaneous", "unit:" + (unit or "none"), op["symbol"]]


def _render(original, evidence):
    family, profile, payload = original["logic_family"], original["profile"], original["payload"]
    require(family in {"deontic", "temporal"} and profile == "modal_ir_" + family + "_structural",
            "unsupported_legal_qualifier_route")
    base._closed(payload, {"schema", "document_id", "partition", "formulas"}, "ModalIR_partition")
    require(payload["schema"] == "modal-ir-family-partition/v3" and payload["partition"] == family,
            "native_ModalIR_partition_required")
    base._text(payload["document_id"], "ModalIR_document_id")
    formulas = base._list(payload["formulas"], "original_formulas")
    require(len(formulas) == len(evidence["formulas"]), "exhaustive_formula_interpretation_required")
    lines, operators, literal_bindings = [], [], {}
    for index, (formula, declaration) in enumerate(zip(formulas, evidence["formulas"])):
        require(declaration["original_formula_sha256"] == digest(formula), "original_formula_digest_differs")
        require(formula.get("provenance", {}).get("source_id") == payload["document_id"], "ModalIR_formula_source_differs")
        body, ops = _formula(formula, declaration, family, literal_bindings)
        lines.append(f"def qualifiedLegalFormula_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := " + body)
        lines.append(f"def originalFormulaProvenance_{index} : String := " + string(base._wire(formula["provenance"]).decode()))
        operators.extend(ops)
    return "\n".join(lines), operators


def prepare_qualified_payload(row, evidence, *, expected_source_ref):
    """Bind every original qualifier; the expected source must come from replay."""
    _guard()
    require(type(evidence) is LegalQualifierInterpretation and type(expected_source_ref) is SourceRef,
            "exact_immutable_legal_interpretation_and_native_source_required")
    expected_source_ref.validate()
    value = evidence.to_dict()
    require(value["source_ref"] == expected_source_ref.to_dict(), "interpretation_source_ref_differs")
    require(type(row) is dict and value["original_projection_id"] == row.get("projection_id") and
            value["original_source_digest"] == row.get("source_digest") and
            value["original_payload_sha256"] == digest(row.get("payload")), "interpretation_original_projection_binding_differs")
    require({"projection_id", "source_digest", "logic_family", "profile", "payload"} <= set(row), "complete_original_projection_required")
    original = {key: row[key] for key in ("projection_id", "source_digest", "logic_family", "profile", "payload")}
    require(len(base._wire(original)) <= 262144, "bounded_original_projection_required")
    _render(original, value)
    payload = {"schema": PAYLOAD_SCHEMA, "original": original, "interpretation": value,
        "interpretation_sha256": evidence.sha256, "source_semantics_verified": False,
        "source_text_inference_executed": False, "admitted": False}
    return {"projection_id": row["projection_id"] + "/explicit-legal-interpretation/v1",
        "logic_family": row["logic_family"], "profile": "explicit_qualified_legal/v2",
        "payload": json.loads(base._wire(payload)), "producer_id": __name__,
        "qualification_gaps": ["caller_supplied_interpretation_not_source_fidelity", "actual_Lake_execution_required",
            "predicate_and_modal_interpretations_not_verified", "no_real_occurrences_or_norm_truth_asserted"],
        "producer_pins": {__name__: _SOURCE_SHA, base.__name__: base._SOURCE_SHA}}


def emit_projection(row, *, report=None):
    payload = row.get("payload")
    if type(payload) is not dict or payload.get("schema") != PAYLOAD_SCHEMA:
        raise NotImplementedError
    _guard()
    base._closed(payload, {"schema", "original", "interpretation", "interpretation_sha256", "source_semantics_verified",
        "source_text_inference_executed", "admitted"}, "legal_qualified_payload")
    require(all(payload[key] is False for key in ("source_semantics_verified", "source_text_inference_executed", "admitted")),
            "explicit_interpretation_cannot_assert_source_fidelity_or_admission")
    base._closed(payload["original"], {"projection_id", "source_digest", "logic_family", "profile", "payload"}, "original_projection")
    evidence = LegalQualifierInterpretation.from_dict(payload["interpretation"])
    expected = prepare_qualified_payload(payload["original"], evidence,
        expected_source_ref=base._source(payload["interpretation"]["source_ref"]))
    require(all(row.get(key) == expected[key] for key in ("projection_id", "logic_family", "profile", "payload")),
            "legal_qualified_projection_replay_differs")
    code, operators = _render(payload["original"], evidence.to_dict())
    return code, {"validator": "exact_native_record_and_explicit_legal_qualifier_replay",
        "operators": operators, "payload_sha256": digest(payload), "capability_floor_eligible": False,
        "interpretation_sha256": evidence.sha256, "source_semantics_verified": False,
        "source_text_inference_executed": False, "runtime_authority_granted": False,
        "event_occurrences_attested": False, "admitted": False,
        "assumptions": ["All qualifier expressions, activation scope and exception scope are explicitly supplied by the caller.",
            "All non-temporal conditions hold at the supplied evaluation origin, outside the modal body.",
            "Activation-time waiver is tested outside the modality at the origin; per-tick exemption is inside a universal interval body.",
            "Nat ticks are the declared unit; no business-day, real clock or occurrence attestation is supplied.",
            "Modal operators and atomic predicates remain interpretation parameters, never established obligations or compliance."],
        "semantics_scope": "explicit_legal_qualifier_interpretation_only",
        "missing_capabilities": ["independent_source_fidelity", "all_named_logic_family_floor_evidence"]}


__all__ = ["LegalQualifierInterpretation", "prepare_qualified_payload", "emit_projection", "digest"]
