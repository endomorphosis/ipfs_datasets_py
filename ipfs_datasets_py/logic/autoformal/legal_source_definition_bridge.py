"""Source-bound, section-local unary predicate definitions in native FOL.

This compiler consumes explicit caller declarations. It does not infer that a
statutory phrase denotes a unary category, establish a definition's full legal
meaning, or turn normative rules into FOL. A universal biconditional is a new,
bounded interpretation profile, distinct from the canonical O/P/F profile.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re

from . import legal_family_routes as routes
from . import legal_statutory_context as context
from ..TDFOL import tdfol_core as t
from ..intent_ir.formalize.modal_projections import _ast

SCHEMA = "legal-source-definition-bridge/v1"
PROFILE = "section-local-unary-predicate-definition/v1"
FAMILIES = ("fol", "tdfol")
_FALSE = {k: False for k in ("source_semantics_verified", "admitted", "training_qualified",
                           "cross_family_equivalence_verified", "backend_executed", "proof_authority")}


def wire(value):
    try:
        result = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError("finite JSON required") from error
    if len(result) > 4 * 1024**2:
        raise ValueError("definition request or report exceeds byte bound")
    return result


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def closed(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "closed " + label + " required")


def producer_pins():
    return routes.producer_pins() | {str(Path(module.__file__).resolve()):
        hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in (context,)} | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_PINS = producer_pins()


def _span(span, text, start, end):
    closed(span, ("char_start", "char_end", "text"), "definition source span")
    left, right = span["char_start"], span["char_end"]
    require(type(left) is int and type(right) is int and start <= left < right <= end,
            "definition span must remain inside its declared source region")
    require(text[left:right] == span["text"] and bool(span["text"].strip()), "exact definition source span differs")
    require(len(span["text"].encode()) <= 4096, "bounded source literal required")
    return span["text"]


def prepare_definition(request):
    """Build and losslessly reparse ∀x(head(x) ↔ body(x)) in declared scope.

    Predicates are qualified by the immutable document and explicit section
    scope span. Equal surface terms in different document versions never share
    a symbol by accident. One untyped Entity carrier is used, not legal sorts.
    """
    require(producer_pins() == _PINS, "definition bridge source changed since import")
    wire(request)
    closed(request, ("document", "raw_html_base64", "declaration", "family"), "definition request")
    require(type(request["family"]) is str and request["family"] in FAMILIES,
            "definition profile supports only FOL and the FOL subset of TDFOL")
    require(type(request["raw_html_base64"]) is str, "base64 official HTML required")
    try:
        raw = base64.b64decode(request["raw_html_base64"], validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("invalid base64 official HTML") from error
    doc, decl = request["document"], request["declaration"]
    context.validate_document(doc, raw)
    closed(decl, ("declaration_id", "profile", "interpretation_status", "paragraph_index", "scope_span",
                  "definition_cue", "head", "body"), "unary definition declaration")
    require(type(decl["declaration_id"]) is str and 0 < len(decl["declaration_id"]) <= 256, "bounded declaration identity required")
    require(decl["profile"] == PROFILE and decl["interpretation_status"] == "unreviewed_caller_declaration",
            "explicit unreviewed unary-predicate interpretation required")
    index = decl["paragraph_index"]
    require(type(index) is int and 0 <= index < len(doc["paragraphs"]), "known definition paragraph required")
    paragraph = doc["paragraphs"][index]
    require(paragraph["kind"] == "codified_body", "codified-body definition required; notes need another profile")
    block = next(row for row in doc["blocks"] if row["paragraph_index"] == index)
    text, start, end = doc["document_text"], block["char_start"], block["char_end"]
    scope = decl["scope_span"]
    require(_span(scope, text, 0, len(text)) in ("In this section", "In this section:"),
            "explicit literal section-local scope required")
    ancestors = [row for row in doc["blocks"] if row["char_start"] <= start and row["char_end"] >= end]
    require(any(row["char_start"] <= scope["char_start"] < scope["char_end"] <= row["char_end"] for row in ancestors),
            "definition scope must occur in its enclosing official block")
    cue = _span(decl["definition_cue"], text, paragraph["char_start"], paragraph["char_end"])
    require(cue == "means", "explicit means cue required; deeming/shall/normative conversion unsupported")
    head_text = _span(decl["head"], text, start, end)
    require(scope["char_end"] <= decl["head"]["char_start"], "section scope must precede its defined term")
    require(decl["head"]["char_end"] <= decl["definition_cue"]["char_start"], "defined term must precede means cue")
    scope_key = digest({"document_id": doc["document_id"], "scope": scope, "profile": PROFILE})
    symbols, atom_spans, node_count = {}, [], 0
    x = t.Variable("x")

    def atom(span, *, head=False):
        literal = _span(span, text, start, end)
        if not head:
            require(span["char_start"] >= decl["definition_cue"]["char_end"], "definition-body atom must follow means cue")
        symbol = "D" + digest({"scope": scope_key, "literal": literal, "arity": 1})
        symbols[symbol] = {"symbol": symbol, "source_literal": literal, "arity": 1, "scope_key": scope_key}
        atom_spans.append({"symbol": symbol, "span": span, "role": "head" if head else "body"})
        return t.Predicate(symbol, (x,))

    def expression(value, depth=0):
        nonlocal node_count
        node_count += 1
        require(depth <= 12 and node_count <= 128 and type(value) is dict, "bounded typed definition expression required")
        op = value.get("op")
        if op == "atom":
            closed(value, ("op", "span"), "definition atom")
            return atom(value["span"])
        if op == "not":
            closed(value, ("op", "operand"), "definition negation")
            return t.UnaryFormula(t.LogicOperator.NOT, expression(value["operand"], depth + 1))
        require(op in ("all", "any"), "unsupported definition expression; no modalities, quantifier erasure or temporal reification")
        closed(value, ("op", "operands"), "definition Boolean expression")
        require(type(value["operands"]) is list and 2 <= len(value["operands"]) <= 16, "bounded nontrivial Boolean operands required")
        operands = [expression(child, depth + 1) for child in value["operands"]]
        result = operands[0]
        for operand in operands[1:]:
            result = t.BinaryFormula(t.LogicOperator.AND if op == "all" else t.LogicOperator.OR, result, operand)
        return result

    head, body = atom(decl["head"], head=True), expression(decl["body"])
    require(all(row["source_literal"] != head_text for symbol, row in symbols.items() if symbol != head.name),
            "definition body cannot silently collapse to its head")
    require(len(symbols) >= 2 and head.name not in {s["symbol"] for s in atom_spans if s["role"] == "body"},
            "self-referential or vacuous head definition unsupported")
    typed = t.QuantifiedFormula(t.Quantifier.FORALL, x, t.BinaryFormula(t.LogicOperator.IFF, head, body))
    native = routes.prepare_native_fragment(family=request["family"], formula=typed.to_string(), expected_ast=_ast(typed))
    report = {"schema": SCHEMA, "profile": PROFILE, "family": request["family"],
        "declaration_id": decl["declaration_id"], "request_sha256": digest(request),
        "document_id": doc["document_id"], "document_text_sha256": doc["document_text_sha256"],
        "definition_block": block, "scope_span": scope, "scope_key": scope_key,
        "definition_cue": decl["definition_cue"], "declaration": decl,
        "symbols": [symbols[key] for key in sorted(symbols)], "symbol_occurrences": atom_spans,
        "native": native, "native_ast": native["native_ast"], "lean_body": native["lean_body"],
        "source_bound": True, "explicit_universal_biconditional": True,
        "declaration_regeneration_verified": True, "producer_pins": _PINS,
        "interpretation_contract": "At each evaluation point, for every entity in one carrier, the section-local head predicate holds iff the explicit Boolean body holds. Predicates are caller-interpreted category labels.",
        "limitations": ["A definition cue and exact source spans do not establish the legal meaning of a category predicate.",
            "This profile does not implement identity/equality, named-individual aliases, multiple legal sorts, or general statutory definitions.",
            "Scope-qualified symbols prevent accidental sharing; cross-section definition resolution requires a separate interpretation.",
            "Caller Boolean structure is preserved, not inferred from legal coordination.",
            "No deontic rules are projected into FOL and no legal truth or source completeness is asserted."], **_FALSE}
    report["report_sha256"] = digest(report)
    wire(report)
    return report


def validate_definition(report, request):
    require(wire(report) == wire(prepare_definition(request)), "definition report differs from authoritative source/declaration regeneration")
    return True
