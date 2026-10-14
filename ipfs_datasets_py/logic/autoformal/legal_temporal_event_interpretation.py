"""Explicit source-bound until properties, never inferred legal translations.

Surface requests retain every proposal and exclusion. Only a complete caller
declaration can give an eligible until proposal a temporal property. State
holding and event occurrence have separate interpretation parameters. Neither
source spans nor supplied predicate identifiers attest a real-world event,
identify a canonical rule owner, or establish the meaning of a law.
"""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import re

from . import family_qualification as family
from . import legal_temporal_event_owner_adapter_v4 as adapter
from . import legal_temporal_occurrence_provenance as provenance
from ..formalization.autoencoder import native_family_lean_emitters as lean
from ..software_verification.temporal import TemporalFormula

REQUEST_SCHEMA = "legal-temporal-event-interpretation-requests/v1"
DECLARATION_SCHEMA = "legal-temporal-event-interpretation-declaration/v1"
ARTIFACT_SCHEMA = "legal-temporal-event-interpretation/v1"
PROFILE = "caller-declared-until-event-property/v1"
_MEANING_FIELDS = (
    "subject_source_span", "subject_source_text", "state_atom", "event_atom",
    "until_strength", "endpoint", "time_domain", "origin", "modal_scope",
)
_BINDING_FIELDS = (
    "request_id", "request_sha256", "source_id", "document_id",
    "source_text_sha256", "document_text_sha256", "occurrence_receipt_sha256",
    "proposal_receipt_sha256",
)
_FALSE = {
    "semantic_gold": False, "source_semantics_verified": False,
    "owner_occurrence_resolved": False, "event_reference_resolved": False,
    "event_occurrences_attested": False, "temporal_origin_resolved": False,
    "scope_resolved": False, "formula_admission": False,
    "family_coverage_gate": False, "family_qualified": False,
    "qualified": False, "admitted": False, "formalized": False,
    "model_execution_verified": False, "runtime_authority_granted": False,
    "source_text_inference_executed": False, "wall_clock_conversion_executed": False,
    "lake_executed": False,
}
_ATOM = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _copy(value):
    return json.loads(_wire(value))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, keys, label):
    _require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def _seal(value):
    return {**value, "receipt_sha256": digest(value)}


def _dependency_pins():
    # Explicitly include validators, typed identity/trace dependencies, the
    # selector and actual Lean prelude. Adapter pins include its metric/type
    # validation chain; proposer pins include the lexical corpus producer.
    modules = (
        "ipfs_datasets_py.logic.autoformal.family_qualification",
        "ipfs_datasets_py.logic.autoformal.tree_pin",
        "ipfs_datasets_py.logic.autoformal.legal_temporal_occurrence_provenance",
        "ipfs_datasets_py.logic.deontic.utils.deontic_parser",
        "ipfs_datasets_py.logic.legal_document",
        "ipfs_datasets_py.logic.TDFOL.tdfol_parser",
        "ipfs_datasets_py.logic.TDFOL.tdfol_core",
        "ipfs_datasets_py.logic.software_verification.temporal",
        "ipfs_datasets_py.logic.software_verification.trace",
        "ipfs_datasets_py.logic.ir_core.canonical",
        "ipfs_datasets_py.logic.ir_core.identity",
        "ipfs_datasets_py.logic.ir_core.claims",
        "ipfs_datasets_py.logic.formalization.autoencoder.native_family_lean_emitters",
    )
    paths = [Path(importlib.import_module(name).__file__).resolve() for name in modules]
    paths.append(Path(__file__).resolve())
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} | adapter.producer_pins()


_INITIAL_PINS = _dependency_pins()
_INITIAL_PRELUDE = lean.PRELUDE


def producer_pins():
    _require(_dependency_pins() == _INITIAL_PINS and lean.PRELUDE == _INITIAL_PRELUDE,
             "temporal event interpretation producer changed")
    return dict(_INITIAL_PINS)


def _span(value, source_text, *, before=None):
    _closed(value, {"char_start", "char_end"}, "source span")
    start, end = value["char_start"], value["char_end"]
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(source_text),
             "exact nonempty source span required")
    if before is not None:
        _require(end <= before, "subject source span must precede temporal span")
    tokens = list(re.finditer(r"\w+|[^\w\s]", source_text, re.UNICODE))
    _require(start in {token.start() for token in tokens} and end in {token.end() for token in tokens},
             "source span must be token aligned")
    return start, end


def _source_anchor(interval, receipt, source_text, document_text):
    if interval is None:
        return None
    start, end = _span(interval, source_text)
    binding = receipt["source_binding"]
    doc_start = provenance._document_boundary(start, binding, source_text, document_text)
    doc_end = provenance._document_boundary(end, binding, source_text, document_text)
    resolved = doc_start is not None and doc_end is not None
    return {
        "source_observation_id": "source-span-observation-sha256:" + digest({
            "source_text_sha256": binding["source_text_sha256"],
            "coordinate_system": binding["source_coordinate_system"],
            "char_start": start, "char_end": end,
        }),
        "document_observation_id": "document-span-observation-sha256:" + digest({
            "document_text_sha256": binding["document_text_sha256"],
            "coordinate_system": binding["document_coordinate_system"],
            "char_start": doc_start, "char_end": doc_end,
        }) if resolved else None,
        "source_span": _copy(interval), "source_text": source_text[start:end],
        "document_span": {"char_start": doc_start, "char_end": doc_end} if resolved else None,
        "document_text": document_text[doc_start:doc_end] if resolved else None,
        "document_translation_resolved": resolved,
    }


def _skeleton(request, receipt, proposal_receipt):
    binding = receipt["source_binding"]
    return {
        "schema": DECLARATION_SCHEMA,
        "request_id": request["request_id"], "request_sha256": request["request_sha256"],
        **{key: binding[key] for key in ("source_id", "document_id", "source_text_sha256", "document_text_sha256")},
        "occurrence_receipt_sha256": receipt["receipt_sha256"],
        "proposal_receipt_sha256": digest(proposal_receipt),
        **dict.fromkeys(_MEANING_FIELDS),
    }


def build_interpretation_requests(receipt, proposal_receipt, *, source_text,
                                  document_text=None, rule_rows=()):
    """Authenticate and inventory proposals without filling any meaning field.

An unmatched legacy-parser occurrence remains unmatched. An exact source-only
until proposal can still request an interpretation, because that request is
bound directly to the authenticated proposer interval and event complement.
"""
    pins = producer_pins()
    joined = provenance.join_adapter_diagnostics(
        receipt, proposal_receipt, source_text=source_text,
        document_text=document_text, rule_rows=rule_rows)
    document_text = source_text if document_text is None else document_text
    by_occurrence = {item["occurrence_id"]: item for item in receipt["occurrences"]}
    requests = []
    for row in joined["rows"]:
        proposal = row["proposal"]
        occurrence = by_occurrence.get(row["occurrence_id"])
        excluded = bool(row["adapter_eligibility"]["exclusion_reasons"]) or (
            occurrence is not None and occurrence["association_status"] == "parser_excluded")
        status = ("excluded" if excluded else "unsupported_family" if proposal["family"] != "until_event"
                  else "awaiting_caller_interpretation")
        reasons = list(row["reason_codes"])
        reasons += row["adapter_eligibility"]["exclusion_reasons"]
        if status == "unsupported_family":
            reasons.append("only_until_event_property_supported")
        if status == "awaiting_caller_interpretation":
            reasons.append("all_meaning_fields_require_caller_declaration")
        body = {
            "profile": PROFILE, "proposal_index": row["proposal_index"],
            "query_id": row["query_id"], "proposal_family": proposal["family"],
            "proposal_status": proposal["status"], "status": status,
            "source_binding": _copy(receipt["source_binding"]),
            "occurrence_receipt_sha256": receipt["receipt_sha256"],
            "proposal_receipt_sha256": digest(proposal_receipt),
            "temporal_source": _source_anchor(proposal["query"]["proposed_time_span"], receipt, source_text, document_text),
            "event_source": _source_anchor(proposal["event_span"], receipt, source_text, document_text),
            "cue_source": _source_anchor(proposal["cue_span"], receipt, source_text, document_text),
            "parser_join": {
                "status": row["status"], "occurrence_id": row["occurrence_id"],
                "association_status": None if occurrence is None else occurrence["association_status"],
                "candidate_rule_associations": [] if occurrence is None else _copy(occurrence["candidate_rule_associations"]),
            },
            "surface_semantic_flags": _copy(proposal["semantic_flags"]),
            "adapter_eligibility": _copy(row["adapter_eligibility"]),
            "reason_codes": sorted(set(reasons)), "authority": dict(_FALSE),
            "producer_pins": pins,
        }
        request = {"request_id": "temporal-interpretation-request-sha256:" + digest(body), **body}
        request["request_sha256"] = digest(request)
        request["declaration_skeleton"] = _skeleton(request, receipt, proposal_receipt)
        requests.append(request)
    _require(producer_pins() == pins, "temporal event interpretation producer changed during request construction")
    return _seal({
        "schema": REQUEST_SCHEMA, "profile": PROFILE,
        "source_binding": _copy(receipt["source_binding"]),
        "occurrence_receipt_sha256": receipt["receipt_sha256"],
        "proposal_receipt_sha256": digest(proposal_receipt),
        "diagnostic_join_sha256": joined["receipt_sha256"],
        "requests": requests, "excluded": _copy(joined["excluded"]),
        "issues": _copy(joined["issues"]),
        "unmatched_occurrence_ids": _copy(joined["unmatched_occurrence_ids"]),
        "counts": {
            "requests": len(requests), "awaiting_caller_interpretation": sum(
                request["status"] == "awaiting_caller_interpretation" for request in requests),
            "unsupported_family": sum(request["status"] == "unsupported_family" for request in requests),
            "excluded": sum(request["status"] == "excluded" for request in requests),
            "issues": len(joined["issues"]),
        },
        "model_calls": 0, "source_binding_is_owner_resolution": False,
        "authority": dict(_FALSE), "producer_pins": pins,
    })


def prepare_event_interpretation(receipt, proposal_receipt, declaration, *, source_text,
                                 document_text=None, rule_rows=()):
    """Compile only a complete explicit declaration against regenerated requests.

The typed AST/TDFOL formula carry distinct nullary symbols, whose roles are
bound in ``atom_roles``. The Lean property interprets those roles through
separate holds/occurs traces; generic TDFOL syntax does not supply that typing.
"""
    inventory = build_interpretation_requests(
        receipt, proposal_receipt, source_text=source_text,
        document_text=document_text, rule_rows=rule_rows)
    _closed(declaration, {"schema", *_BINDING_FIELDS, *_MEANING_FIELDS}, "event interpretation declaration")
    _require(declaration["schema"] == DECLARATION_SCHEMA, "event interpretation declaration schema differs")
    matches = [request for request in inventory["requests"] if request["request_id"] == declaration["request_id"]]
    _require(len(matches) == 1, "exact interpretation request ID required")
    request = matches[0]
    _require(all(declaration[key] == request["declaration_skeleton"][key] for key in _BINDING_FIELDS),
             "interpretation request/source binding differs")
    _require(request["status"] == "awaiting_caller_interpretation", "unsupported or excluded interpretation request")
    _require(all(declaration[key] is not None for key in _MEANING_FIELDS), "complete caller meaning declaration required")
    expected = {
        "endpoint": "exclude_event_tick", "time_domain": "discrete_unbounded_nat",
        "origin": "caller_supplied_evaluation_time", "modal_scope": "temporal_property_only",
    }
    _require(all(declaration[key] == value for key, value in expected.items()),
             "unsupported endpoint/time domain/origin/modal scope")
    _require(type(declaration["until_strength"]) is str and declaration["until_strength"] in {"weak", "strong"},
             "explicit weak or strong until required")
    for field in ("state_atom", "event_atom"):
        _require(type(declaration[field]) is str and _ATOM.fullmatch(declaration[field]) is not None,
                 "bounded distinct identifier atoms required")
    _require(declaration["state_atom"] != declaration["event_atom"], "state and event atoms must be distinct")
    start, end = _span(declaration["subject_source_span"], source_text,
                       before=request["temporal_source"]["source_span"]["char_start"])
    _require(type(declaration["subject_source_text"]) is str and
             declaration["subject_source_text"] == source_text[start:end], "exact subject source text differs")
    event_source = request["event_source"]
    _require(event_source is not None, "exact event complement required")
    subject_source = _source_anchor(declaration["subject_source_span"], receipt, source_text,
                                    source_text if document_text is None else document_text)
    state, event = declaration["state_atom"], declaration["event_atom"]
    strong = declaration["until_strength"] == "strong"
    operator = "until" if strong else "weak_until"
    ast = TemporalFormula(operator=operator, operands=(
        TemporalFormula(operator="atom", proposition=state),
        TemporalFormula(operator="atom", proposition=event),
    )).to_dict()
    _require(TemporalFormula.from_dict(ast).to_dict() == ast, "typed temporal AST roundtrip differs")
    concrete = "(" + state + (" U " if strong else " W ") + event + ")"
    diagnostics = [family.validate_family_artifact(name, concrete)
                   for name in ("temporal_fol", "deontic_temporal_fol")]
    _require(all(result["passed"] and result["syntax_valid"] for result in diagnostics),
             "strict event temporal formula validation failed")
    parsed, strict_receipt = family._strict_tdfol(concrete)
    _require(type(parsed).__name__ == "BinaryTemporalFormula" and
             parsed.operator.value == ("U" if strong else "W") and
             all(type(node).__name__ == "Predicate" and not node.arguments
                 for node in (parsed.left, parsed.right)) and
             (parsed.left.name, parsed.right.name) == (state, event) and parsed.to_string() == concrete,
             "strict temporal operator/atom shape differs")
    lean_operator = "untilTime" if strong else "weakUntilTime"
    declarations = (
        "structure EventInterpretation where\n"
        "  holds : String → Nat → Prop\n"
        "  occurs : String → Nat → Prop\n\n"
        "def eventTemporalProperty (trace : EventInterpretation) : Nat → Prop :=\n"
        "  " + lean_operator + " (trace.holds " + lean.string(state) + ") (trace.occurs " + lean.string(event) + ")\n"
    )
    return _seal({
        "schema": ARTIFACT_SCHEMA, "profile": PROFILE,
        "declaration": _copy(declaration), "declaration_sha256": digest(declaration),
        "request": _copy(request), "request_inventory_sha256": inventory["receipt_sha256"],
        "source_binding": _copy(receipt["source_binding"]),
        "subject_source": subject_source, "event_source": _copy(event_source),
        "subject_anchor_scope": "source_anchor_only_not_canonical_legal_owner",
        "atom_roles": {state: "state_holds", event: "event_occurs"},
        "temporal_ast": ast, "tdfol_formula": concrete,
        "family_diagnostics": diagnostics, "strict_tdfol_receipt": strict_receipt,
        "lean_declarations": declarations, "lean_source": lean.PRELUDE + "\n" + declarations,
        "lean_prelude_sha256": hashlib.sha256(lean.PRELUDE.encode()).hexdigest(),
        "semantics": {
            "scope": "caller_supplied_interpretation_not_source_translation",
            "time_domain": "discrete_unbounded_nat", "origin": "caller_supplied_evaluation_time",
            "until_strength": declaration["until_strength"], "endpoint": "exclude_event_tick",
            "modal_scope": "temporal_property_only", "separate_holds_and_occurs": True,
            "event_at_origin_allows_empty_holding_interval": True,
            "event_eventually_required_by_property": strong,
            "syntax_atom_roles_supplied_separately": True,
        },
        "assumptions": [
            "The caller supplies the temporal property; source fidelity and legal ownership remain unresolved.",
            "holds and occurs are independent arbitrary Nat traces, not established states or attested events.",
            "The origin is the caller's evaluation time; Nat ticks are not wall-clock units.",
            "The event tick is excluded. Strong until requires an event; weak until also permits holding forever.",
            "Family diagnostics check the concrete U/W syntax only and confer no family qualification.",
            "No modality, event-calculus axiom, actual event, law, or compliance proposition is asserted.",
        ],
        "model_calls": 0, "authority": dict(_FALSE), "producer_pins": producer_pins(),
    })


def validate_event_interpretation(artifact, receipt, proposal_receipt, *, source_text,
                                 document_text=None, rule_rows=()):
    """Regenerate the entire artifact; altered AST, Lean, flags or pins fail."""
    _require(type(artifact) is dict and artifact.get("schema") == ARTIFACT_SCHEMA,
             "versioned event interpretation artifact required")
    expected = prepare_event_interpretation(
        receipt, proposal_receipt, artifact.get("declaration"), source_text=source_text,
        document_text=document_text, rule_rows=rule_rows)
    _require(_wire(artifact) == _wire(expected), "event interpretation artifact differs from exact replay")
    return _copy(expected)


__all__ = ["build_interpretation_requests", "prepare_event_interpretation",
           "validate_event_interpretation", "producer_pins", "digest",
           "REQUEST_SCHEMA", "DECLARATION_SCHEMA", "ARTIFACT_SCHEMA", "PROFILE"]
