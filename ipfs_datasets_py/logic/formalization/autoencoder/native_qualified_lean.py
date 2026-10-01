"""Explicit, source-bound interpretations of previously opaque qualifiers.

The caller supplies these interpretations; this module does not infer them from
prose. Exact source and native-record joins establish internal consistency, not
source fidelity, authenticity, legal validity, or proof of a declared norm.
Unqualified original projections remain unsupported in the existing emitter.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from . import native_family_lean_emitters as old
from ...ir_core.provenance import SourceRef

EVIDENCE_SCHEMA = "explicit-projection-interpretation/v1"
PAYLOAD_SCHEMA = "qualified-projection-interpretation/v1"
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_SHA = re.compile(r"[0-9a-f]{64}")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:/-]{0,255}")
_ATOM = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")
require, string = old.require, old.string


def _guard():
    require(hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == _SOURCE_SHA,
            "explicit_interpretation_producer_changed")


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _closed(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "closed_" + label + "_required")


def _list(value, label, *, empty=False, bound=64):
    require(type(value) is list and (empty or value) and len(value) <= bound,
            "bounded_" + label + "_required")
    return value


def _text(value, label):
    require(type(value) is str and value.strip() and len(value.encode()) <= 4096,
            "bounded_" + label + "_required")
    string(value)
    return value


def _sha(value):
    require(type(value) is str and _SHA.fullmatch(value), "exact_sha256_required")


def _source(value):
    require(type(value) is dict, "exact_source_ref_required")
    result = SourceRef.from_dict(value)
    require(result.to_dict() == value, "source_ref_roundtrip_differs")
    return result


def _evidence(value):
    _closed(value, {"schema", "source_ref", "original_projection_id", "original_source_digest",
        "original_payload_sha256", "declaration_scope", "formulas"}, "interpretation")
    require(value["schema"] == EVIDENCE_SCHEMA, "explicit_interpretation_schema_required")
    _source(value["source_ref"])
    _text(value["original_projection_id"], "original_projection_id")
    _sha(value["original_source_digest"]); _sha(value["original_payload_sha256"])
    require(value["declaration_scope"] == "caller_supplied_interpretation_not_source_translation",
            "explicit_interpretation_scope_required")
    for index, row in enumerate(_list(value["formulas"], "formula_interpretations")):
        require(type(row) is dict and {"formula_index", "original_formula_sha256", "kind"} <= set(row)
                and type(row.get("formula_index")) is int and row["formula_index"] == index,
                "exhaustive_ordered_formula_interpretations_required")
        _sha(row.get("original_formula_sha256"))


@dataclass(frozen=True, slots=True)
class ExplicitProjectionInterpretation:
    """Canonical immutable bytes; every decoded view is an independent copy."""
    _bytes: bytes

    def __post_init__(self):
        require(type(self._bytes) is bytes and len(self._bytes) <= 262144,
                "bounded_interpretation_bytes_required")
        value = json.loads(self._bytes)
        _evidence(value)
        require(_wire(value) == self._bytes, "canonical_interpretation_bytes_required")

    @classmethod
    def from_dict(cls, value):
        return cls(_wire(value))

    def to_dict(self):
        return json.loads(self._bytes)

    @property
    def sha256(self):
        return hashlib.sha256(self._bytes).hexdigest()


def _predicate(value):
    _closed(value, {"name", "arguments"}, "declared_predicate")
    require(type(value["name"]) is str and _ATOM.fullmatch(value["name"]), "explicit_atomic_predicate_name_required")
    args = _list(value["arguments"], "predicate_arguments", empty=True, bound=16)
    for arg in args:
        _text(arg, "predicate_argument")
    return "(fun t => i.atom " + string(value["name"]) + " [" + ", ".join(
        "i.constant " + string(arg) for arg in args) + "] t)"


def _legal_formula(row, declaration, family):
    _closed(row, {"conditions", "exceptions", "formula_id", "metadata", "operator", "predicate", "provenance"}, "ModalIR_formula")
    _text(row["formula_id"], "formula_id")
    require(row["metadata"] == {}, "uninterpreted_ModalIR_metadata")
    _closed(row["provenance"], {"source_id", "start_char", "end_char", "citation"}, "ModalIR_provenance")
    _closed(row["operator"], {"family", "system", "symbol", "label"}, "ModalIR_operator")
    _closed(row["predicate"], {"name", "arguments", "role"}, "ModalIR_predicate")
    require(row["predicate"]["role"] in (None, "clause"), "unsupported_ModalIR_predicate_role")
    atom = _predicate({k: row["predicate"][k] for k in ("name", "arguments")})
    op = row["operator"]
    legal_ops = {"O": "obligation", "P": "permission", "F": "prohibition"}
    temporal_ops = {"F": "eventually", "G": "always"}
    require(op["family"] == family and (
        family == "deontic" and op["system"] == "D" and legal_ops.get(op["symbol"]) == op["label"] or
        family == "temporal" and op["system"] == "LTL" and temporal_ops.get(op["symbol"]) == op["label"]),
        "unsupported_qualified_native_operator")
    _closed(declaration, {"formula_index", "original_formula_sha256", "kind", "temporal", "exception_scope", "exceptions"}, "legal_interpretation")
    require(declaration["kind"] == "bounded_temporal_qualification", "explicit_legal_qualification_required")
    temporal = declaration["temporal"]
    _closed(temporal, {"source_text", "temporal_kind", "quantity", "unit", "time_domain", "origin",
        "lower_inclusive", "upper_inclusive"}, "temporal_interpretation")
    require(temporal["time_domain"] == "discrete_nat" and temporal["origin"] == "caller_supplied_evaluation_time",
            "explicit_discrete_clock_and_origin_required")
    require(temporal["lower_inclusive"] is True and temporal["upper_inclusive"] is True,
            "only_explicit_closed_intervals_supported")
    quantity, unit, kind = temporal["quantity"], temporal["unit"], temporal["temporal_kind"]
    require(type(quantity) is int and 1 <= quantity <= 1000000, "positive_bounded_temporal_quantity_required")
    require(unit in {"day", "hour"} and kind in {"within_duration", "minimum_duration"}, "supported_explicit_kind_and_unit_required")
    duration = str(quantity) + " " + unit + ("s" if quantity != 1 else "")
    expected = "within " + duration if kind == "within_duration" else "for at least " + duration
    require(temporal["source_text"] == expected and row["conditions"] == [expected],
            "temporal_literal_kind_quantity_unit_or_condition_coverage_differs")
    require(family != "temporal" or op["symbol"] == ("F" if kind == "within_duration" else "G"),
            "temporal_operator_disagrees_with_explicit_qualification")
    require(declaration["exception_scope"] == "activation_time_waiver", "explicit_exception_scope_required")
    exceptions = _list(row["exceptions"], "native_exceptions", empty=True, bound=8)
    mappings = _list(declaration["exceptions"], "exception_interpretations", empty=True, bound=8)
    require(len(exceptions) == len(mappings), "exhaustive_exception_interpretations_required")
    rendered_exceptions = []
    for source_text, mapping in zip(exceptions, mappings):
        _closed(mapping, {"source_text", "predicate"}, "exception_interpretation")
        _text(source_text, "native_exception")
        require(mapping["source_text"] == source_text, "ordered_exception_binding_differs")
        rendered_exceptions.append(_predicate(mapping["predicate"]) + " t")
    if kind == "within_duration":
        body = "(fun origin => ∃ u, origin ≤ u ∧ u ≤ origin + " + str(quantity) + " ∧ " + atom + " u)"
    else:
        body = "(fun origin => ∀ u, origin ≤ u → u ≤ origin + " + str(quantity) + " → " + atom + " u)"
    # The clock unit is an explicit interpretation annotation: one Nat tick is
    # exactly one declared unit. There is no wall-clock or business-day bridge.
    if family == "deontic":
        body = "(i.modal " + string("deontic:" + op["symbol"]) + " [] (some " + string("explicit-clock:" + unit) + ") " + body + ")"
    if rendered_exceptions:
        body = "(fun t => ¬ (" + " ∨ ".join("(" + x + ")" for x in rendered_exceptions) + ") → " + body + " t)"
    return body, ["closed_" + kind, "unit:" + unit, "activation_time_waiver", op["symbol"]]


def _ui_formula(row, declaration, expected_source):
    _closed(row, {"operator", "proposition", "strength", "source_ref_ids"}, "UI_norm")
    require(row["operator"] in {"obligation", "permission", "prohibition"} and row["strength"] in {"strict", "weak"},
            "unsupported_UI_modality_or_strength")
    refs = _list(row["source_ref_ids"], "UI_native_source_refs", bound=16)
    require(all(type(ref) is str and _ID.fullmatch(ref) for ref in refs) and len(set(refs)) == len(refs),
            "exact_native_UI_source_identifiers_required")
    common = {"formula_index", "original_formula_sha256", "kind"}
    if declaration["kind"] == "atomic_UI_norm":
        _closed(declaration, common, "atomic_UI_interpretation")
        match = re.fullmatch(r"(invoke|weaken_norm)\(([A-Za-z][A-Za-z0-9_.:/-]{0,255})\)", row["proposition"])
        require(match is not None, "single_native_UI_action_atom_required")
        name, action = match.groups()
        body = _predicate({"name": name, "arguments": [action]})
        operators = ["atomic_UI_norm"]
    else:
        _closed(declaration, common | {"action_id", "policy", "time_domain", "window_origin", "strict_before",
            "correlation", "freshness_modeled", "token_consumption_modeled", "cancellation_modeled"}, "UI_precedence_interpretation")
        require(declaration["kind"] == "UI_confirmation_policy", "explicit_UI_precedence_policy_required")
        action = declaration["action_id"]
        require(type(action) is str and _ID.fullmatch(action), "bounded_UI_action_id_required")
        require(declaration["time_domain"] == "discrete_nat" and declaration["window_origin"] == "caller_supplied_evaluation_time"
                and declaration["strict_before"] is True and declaration["correlation"] == "action_id_only",
                "explicit_UI_time_order_and_correlation_required")
        require(all(declaration[k] is False for k in ("freshness_modeled", "token_consumption_modeled", "cancellation_modeled")),
                "unsupported_UI_freshness_consumption_or_cancellation_semantics")
        confirmed = "(∃ v, origin ≤ v ∧ v < u ∧ i.atom \"confirm\" [i.constant " + string(action) + "] v)"
        invoked = "i.atom \"invoke\" [i.constant " + string(action) + "] u"
        if declaration["policy"] == "every_invocation_has_strict_prior_confirmation":
            require(row["operator"] == "obligation" and row["proposition"] == f"confirm({action}) before invoke({action})",
                    "UI_obligation_policy_literal_differs")
            body = "(fun origin => ∀ u, origin ≤ u → " + invoked + " → " + confirmed + ")"
        elif declaration["policy"] == "unconfirmed_invocation":
            require(row["operator"] == "prohibition" and row["proposition"] == f"invoke({action}) before confirm({action})",
                    "UI_prohibition_policy_literal_differs")
            body = "(fun origin => ∃ u, origin ≤ u ∧ " + invoked + " ∧ ¬ " + confirmed + ")"
        else:
            raise old.UnsupportedNativeLean("unknown_UI_confirmation_policy")
        operators = ["strict_prior_confirmation", declaration["policy"]]
    modality = {"obligation": "O", "permission": "P", "prohibition": "F"}[row["operator"]]
    return "i.modal " + string("deontic:" + modality) + " [] (some " + string("UI-strength:" + row["strength"]) + ") " + body, operators


def _render(original, evidence, expected_source):
    family, profile, payload = original["logic_family"], original["profile"], original["payload"]
    if family in {"deontic", "temporal"} and profile == "modal_ir_" + family + "_structural":
        _closed(payload, {"schema", "document_id", "partition", "formulas"}, "ModalIR_partition")
        require(payload["schema"] == "modal-ir-family-partition/v3" and payload["partition"] == family,
                "native_ModalIR_partition_required")
        _text(payload["document_id"], "ModalIR_document_id")
        route = "legal"
    elif family == "tdfol" and profile == "ui-tdfol-compilation/v1":
        _closed(payload, {"formulas"}, "UI_deontic_payload")
        route = "UI"
    else:
        raise old.UnsupportedNativeLean("unsupported_explicit_interpretation_route")
    formulas = _list(payload["formulas"], "original_formulas")
    require(len(formulas) == len(evidence["formulas"]), "exhaustive_formula_interpretation_required")
    lines, operators = [], []
    for index, (formula, declaration) in enumerate(zip(formulas, evidence["formulas"])):
        require(declaration["original_formula_sha256"] == digest(formula), "original_formula_digest_differs")
        if route == "legal":
            require(formula.get("provenance", {}).get("source_id") == payload["document_id"],
                    "ModalIR_formula_source_differs")
            body, ops = _legal_formula(formula, declaration, family)
        else:
            body, ops = _ui_formula(formula, declaration, expected_source)
        lines.append(f"def qualifiedFormula_{index} {{Entity Agent : Type}} (i : Interpretation Entity Agent) : Nat → Prop := " + body)
        provenance = formula["provenance"] if route == "legal" else formula["source_ref_ids"]
        lines.append(f"def originalFormulaProvenance_{index} : String := " + string(_wire(provenance).decode()))
        operators.extend(ops)
    return "\n".join(lines), operators, route


def prepare_qualified_payload(row, evidence, *, expected_source_ref):
    """Return a new projection descriptor after an exact source/record join.

    Callers must obtain expected_source_ref from the actual replayed source
    inputs, not from the evidence itself. This function never changes the row.
    """
    _guard()
    require(type(evidence) is ExplicitProjectionInterpretation and type(expected_source_ref) is SourceRef,
            "exact_immutable_interpretation_and_native_source_required")
    expected_source_ref.validate()
    value = evidence.to_dict()
    require(value["source_ref"] == expected_source_ref.to_dict(), "interpretation_source_ref_differs")
    require(type(row) is dict and value["original_projection_id"] == row.get("projection_id") and
            value["original_source_digest"] == row.get("source_digest") and
            value["original_payload_sha256"] == digest(row.get("payload")), "interpretation_original_projection_binding_differs")
    require({"projection_id", "source_digest", "logic_family", "profile", "payload"} <= set(row),
            "complete_original_projection_required")
    original = {key: row[key] for key in ("projection_id", "source_digest", "logic_family", "profile", "payload")}
    require(len(_wire(original)) <= 262144, "bounded_original_projection_required")
    _, _, route = _render(original, value, expected_source_ref)
    payload = {"schema": PAYLOAD_SCHEMA, "original": original, "interpretation": value,
        "interpretation_sha256": evidence.sha256, "source_semantics_verified": False,
        "source_text_inference_executed": False, "admitted": False}
    return {"projection_id": row["projection_id"] + "/explicit-interpretation/v1",
        "logic_family": row["logic_family"], "profile": "explicit_qualified_" + route.lower() + "/v1",
        "payload": json.loads(_wire(payload)), "producer_id": __name__,
        "qualification_gaps": ["caller_supplied_interpretation_not_source_fidelity", "actual_Lake_execution_required",
            "predicate_and_modal_interpretations_not_verified", "no_real_occurrences_or_norm_truth_asserted"],
        "producer_pins": {__name__: _SOURCE_SHA}}


def emit_projection(row, *, report=None):
    """Lower only this version's explicit payload; never infer opaque strings."""
    payload = row.get("payload")
    if type(payload) is not dict or payload.get("schema") != PAYLOAD_SCHEMA:
        raise NotImplementedError
    _guard()
    _closed(payload, {"schema", "original", "interpretation", "interpretation_sha256", "source_semantics_verified",
        "source_text_inference_executed", "admitted"}, "qualified_payload")
    require(all(payload[key] is False for key in ("source_semantics_verified", "source_text_inference_executed", "admitted")),
            "explicit_interpretation_cannot_assert_source_fidelity_or_admission")
    _closed(payload["original"], {"projection_id", "source_digest", "logic_family", "profile", "payload"}, "original_projection")
    evidence = ExplicitProjectionInterpretation.from_dict(payload["interpretation"])
    expected = prepare_qualified_payload(payload["original"], evidence,
        expected_source_ref=_source(payload["interpretation"]["source_ref"]))
    require(all(row.get(key) == expected[key] for key in ("projection_id", "logic_family", "profile", "payload")),
            "qualified_projection_replay_differs")
    code, operators, route = _render(payload["original"], evidence.to_dict(),
        _source(payload["interpretation"]["source_ref"]))
    return code, {"validator": "exact_native_record_and_explicit_interpretation_replay",
        "operators": operators, "payload_sha256": digest(payload), "capability_floor_eligible": False,
        "interpretation_sha256": evidence.sha256, "source_semantics_verified": False,
        "source_text_inference_executed": False, "runtime_authority_granted": False,
        "event_occurrences_attested": False, "admitted": False,
        "assumptions": ["Interpretation was explicitly supplied by the caller, not inferred from source text.",
            "Nat evaluation time and its declared unit are supplied by the caller; no real clock or event is attested.",
            "Predicates and modal operators are interpretation parameters, not established facts or legal obligations.",
            "UI prior confirmation is correlated only by action ID; freshness, token consumption and cancellation are not modeled."],
        "semantics_scope": "explicit_" + route.lower() + "_interpretation_only",
        "missing_capabilities": ["independent_source_fidelity", "all_named_logic_family_floor_evidence"]}


__all__ = ["ExplicitProjectionInterpretation", "prepare_qualified_payload", "emit_projection", "digest"]
