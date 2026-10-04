"""Explicit section-local definition-to-quantified-unary-norm composition.

This is a compiler for caller declarations, not a natural-language extractor.
Official-shaped authored HTML is accepted only with explicit fixture provenance;
URL shape and deterministic extraction never authenticate a statutory source.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import legal_source_definition_bridge as definitions
from . import legal_family_routes as routes
from ..TDFOL import tdfol_core as t
from ..intent_ir.formalize.modal_projections import _ast

SCHEMA = "legal-source-definition-norm-bridge/v1"
PROFILE = "section-local-defined-category-unary-norm/v1"
FAMILIES = ("deontic_fol", "tdfol")
CUES = {"O": "shall", "P": "may", "F": "shall not"}
ACTIVATION = "category_at_evaluation_point_outside_modal"
FALSE_FLAGS = {key: False for key in ("source_semantics_verified", "source_authenticity_verified",
    "independently_reviewed", "admitted", "training_qualified", "proof_authority",
    "backend_executed", "learned_translation", "cross_family_equivalence_verified")}
require, closed, wire, digest = definitions.require, definitions.closed, definitions.wire, definitions.digest
_RESERVED = re.compile(r"\b(?:if|unless|except|when|while|until|before|after|within|shall|may|must|not|"
                       r"and|or|provided|subject|including|excluding|each|every|section|paragraph)\b", re.I)


def producer_pins():
    return definitions.producer_pins() | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_PINS = producer_pins()


def prepare_definition_norm(request):
    require(producer_pins() == _PINS, "definition-norm compiler changed since import")
    wire(request)
    closed(request, ("definition_request", "norm_declaration", "family", "source_provenance"), "composition request")
    require(request["family"] in FAMILIES, "quantified normative composition requires deontic_fol or tdfol")
    provenance = request["source_provenance"]
    closed(provenance, ("kind", "authenticity_verified", "independently_reviewed", "training_admitted"), "source provenance")
    require(provenance["kind"] in ("authored_official_shape_fixture", "supplied_html_unreviewed")
            and all(provenance[key] is False for key in provenance if key != "kind"),
            "explicit unauthenticated, unreviewed caller-source provenance required")
    definition = definitions.prepare_definition(request["definition_request"])
    definitions.validate_definition(definition, request["definition_request"])
    doc = request["definition_request"]["document"]
    norm = request["norm_declaration"]
    closed(norm, ("norm_id", "profile", "interpretation_status", "document_id", "document_text_sha256",
                  "legal_id", "edition", "paragraph_index", "source_span", "quantifier_span", "category_span",
                  "modality_span", "action_span", "modality", "variable", "definition_head_symbol",
                  "activation_scope", "modal_context"), "quantified unary norm")
    require(type(norm["norm_id"]) is str and 1 <= len(norm["norm_id"]) <= 256, "bounded norm identity required")
    require(norm["profile"] == PROFILE and norm["interpretation_status"] == "unreviewed_caller_declaration"
            and norm["variable"] == "x" and norm["activation_scope"] == ACTIVATION and norm["modal_context"] is None,
            "explicit universal variable, activation and null modal context required")
    require(all(norm[key] == doc[key] for key in ("document_id", "document_text_sha256", "legal_id", "edition"))
            and type(norm["edition"]) is int, "definition and norm must share exact document, section and version")
    index = norm["paragraph_index"]
    require(type(index) is int and 0 <= index < len(doc["paragraphs"]), "known norm paragraph required")
    paragraph = doc["paragraphs"][index]
    block = next((row for row in doc["blocks"] if row["paragraph_index"] == index), None)
    require(paragraph["kind"] == "codified_body" and block is not None and not block["descendant_paragraphs"],
            "one complete codified leaf paragraph required; nested lists and notes are unsupported")
    text, left, right = doc["document_text"], paragraph["char_start"], paragraph["char_end"]
    head = definition["declaration"]["head"]["text"]
    require(bool(re.fullmatch(r"[A-Za-z]+(?:[ -][A-Za-z]+){0,7}", head)) and not _RESERVED.search(head),
            "bounded literal category name without hidden qualifiers required")
    head_symbol = definition["native_ast"]["formula"]["left"]["name"]
    require(norm["definition_head_symbol"] == head_symbol, "category binding must name exact scoped definition head")
    require(type(norm["modality"]) is str and norm["modality"] in CUES, "explicit O/P/F modality required")
    literals = {key: definitions._span(norm[key], text, left, right) for key in
                ("source_span", "quantifier_span", "category_span", "modality_span", "action_span")}
    action = literals["action_span"]
    require(bool(re.fullmatch(r"[A-Za-z][A-Za-z-]{0,63}", action)) and not _RESERVED.search(action),
            "one declared unary action word required; qualifiers, objects and extra modals unsupported")
    expected = f"Each {head} {CUES[norm['modality']]} {action}."
    prefix = f"({paragraph['leading_label']}) " if paragraph["leading_label"] is not None else ""
    require(paragraph["text"] == prefix + expected and literals["source_span"] == expected
            and norm["source_span"]["char_start"] == left + len(prefix)
            and norm["source_span"]["char_end"] == right,
            "complete norm paragraph coverage differs; extra text cannot be discarded")
    cursor = norm["source_span"]["char_start"]
    for key, literal in (("quantifier_span", "Each"), ("category_span", head),
                         ("modality_span", CUES[norm["modality"]]), ("action_span", action)):
        require(norm[key] == {"char_start": cursor, "char_end": cursor + len(literal), "text": literal},
                "ordered exact quantified-norm token spans required")
        cursor += len(literal) + 1
    require(definition["declaration"]["head"]["char_end"] < left,
            "definition must precede norm in this bounded section-local profile")
    require(len(re.findall(r"In this section\b", text, re.I)) == 1,
            "ambiguous multiple section-scope declarations require a different profile")
    # The legacy definition namespace uses the HTML hash. Identical bytes may
    # legitimately occur in two editions; the composition namespace binds the
    # full declared version, without changing that immutable legacy contract.
    scope = digest({"profile": PROFILE, "legacy_scope_key": definition["scope_key"],
                    **{key: doc[key] for key in ("document_id", "legal_id", "edition", "source_url")}})
    rebinding = {row["symbol"]: "D" + digest({"scope_key": scope, "source_symbol": row["symbol"], "arity": 1})
                 for row in definition["symbols"]}
    bound_definition_ast = json.loads(wire(definition["native_ast"]))
    def bind_ast(node):
        if type(node) is dict:
            if node.get("node_type") == "Predicate":
                require(node["name"] in rebinding, "unknown definition predicate in registry binding")
                node["name"] = rebinding[node["name"]]
            for child in node.values(): bind_ast(child)
        elif type(node) is list:
            for child in node: bind_ast(child)
    bind_ast(bound_definition_ast)
    formula = re.sub(r"\b(?:" + "|".join(map(re.escape, rebinding)) + r")\b",
                     lambda match: rebinding[match.group()], definition["native"]["formula"])
    bound_definition = routes.prepare_native_fragment(family="fol", formula=formula, expected_ast=bound_definition_ast)
    bound_head_symbol = rebinding[head_symbol]
    action_symbol = "N" + digest({"scope_key": scope, "kind": "unary_action", "literal": action, "arity": 1})
    x = t.Variable("x")
    category, action_atom = t.Predicate(bound_head_symbol, (x,)), t.Predicate(action_symbol, (x,))
    modal = t.DeonticFormula(t.DeonticOperator(norm["modality"]), action_atom, agent=None, context=None)
    norm_ast = t.QuantifiedFormula(t.Quantifier.FORALL, x, t.BinaryFormula(t.LogicOperator.IMPLIES, category, modal))
    definition_ast = routes.qualification._strict_tdfol(bound_definition["formula"])[0]
    joint = t.BinaryFormula(t.LogicOperator.AND, definition_ast, norm_ast)
    native = routes.prepare_native_fragment(family=request["family"], formula=joint.to_string(), expected_ast=_ast(joint))
    report = {"schema": SCHEMA, "profile": PROFILE, "family": request["family"], "norm_id": norm["norm_id"],
        "request_sha256": digest(request), "source_provenance": provenance, "document_id": doc["document_id"],
        "document_text_sha256": doc["document_text_sha256"], "legal_id": doc["legal_id"], "edition": doc["edition"],
        "definition": definition, "norm_declaration": norm, "scope_key": scope,
        "definition_symbol_rebinding": rebinding, "bound_definition_native_ast": bound_definition_ast,
        "bound_definition_native": bound_definition,
        "symbol_table": [{**row, "source_symbol": row["symbol"], "symbol": rebinding[row["symbol"]],
                          "scope_key": scope} for row in definition["symbols"]] + [{"symbol": action_symbol, "source_literal": action,
            "arity": 1, "scope_key": scope, "kind": "unary_action"}],
        "variable_binding": {"variable": "x", "category_symbol": bound_head_symbol, "action_symbol": action_symbol,
            "category_mention": norm["category_span"], "definition_head": definition["declaration"]["head"],
            "carrier": "one_untyped_Entity", "ground_actor_constant_substitution": False},
        "norm_native_ast": _ast(norm_ast), "native_ast": native["native_ast"], "native": native,
        "lean_body": native["lean_body"], "complete_norm_paragraph_covered": True,
        "universal_category_guard_outside_modal": True, "source_bound": True,
        "limitations": ["Caller interpretation, not automatic legal-text formalization or legal review.",
            "A section URL shape and source hash do not establish authenticity or complete legal context.",
            "Only the declared norm paragraph has complete lexical coverage; definition completeness is not asserted.",
            "No object, relation, condition, exception, temporal origin, external definition or legal sort resolution.",
            "Parameterized O/P/F semantics; no deontic axioms, legal truth or compliance proof."],
        "producer_pins": _PINS, **FALSE_FLAGS}
    report["report_sha256"] = digest(report)
    wire(report)
    return report


def validate_definition_norm(report, request):
    require(wire(report) == wire(prepare_definition_norm(request)),
            "definition-norm report differs from authoritative regeneration")
    return True
