"""Separate legal-rule routes from independently supplied native fragments.

A canonical O/P/F rule stays deontic. An independently supplied FOL, temporal,
TDFOL, or narrow DCEC fragment can be checked through its actual native parser
and Lean renderer, but that does not make it equivalent to the legal rule.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import family_qualification as qualification
from . import legal_canonical_calendar as calendar
from ..TDFOL import tdfol_parser, tdfol_core
from ..CEC.native import dcec_integration, dcec_core, dcec_parsing, dcec_cleaning, dcec_prototypes
from ..intent_ir.formalize import modal_projections
from ..formalization.autoencoder import native_family_lean_emitters as emitter

SCHEMA = "legal-native-family-route/v1"
_FAMILIES = {"fol", "deontic_fol", "temporal_fol", "tdfol", "dcec"}
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}")


def _pins():
    modules = (qualification, tdfol_parser, tdfol_core, dcec_integration, dcec_core,
               dcec_parsing, dcec_cleaning, dcec_prototypes, modal_projections, emitter)
    return calendar.producer_pins() | {str(Path(module.__file__).resolve()):
        hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for module in modules} | {
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    if _pins() != _IMPORTED_PINS:
        raise ValueError("native family route producer changed since import")
    return dict(_IMPORTED_PINS)


def route_canonical(candidate, interpretation, *, family):
    """Only the deontic route currently preserves this complete legal profile."""
    producer_pins()
    if family != "deontic":
        raise ValueError("canonical O/P/F rules require the deontic route; broader family equivalence is unverified")
    return calendar.prepare_canonical_qualified(candidate, interpretation)


def _print_ground_dcec(node):
    """Lossless printer for the tested ground O/P/F predicate subset.

    The legacy printer adds empty parentheses to constants, which its parser
    rejects. This small printer is always checked against a full native reparse.
    Quantifiers/cognition/events are deliberately outside this route.
    """
    if type(node) is dcec_core.DeonticFormula:
        if node.agent is not None or node.operator.value not in {"O", "P", "F"}:
            raise ValueError("unsupported DCEC modality or agent annotation")
        if type(node.formula) is not dcec_core.AtomicFormula:
            raise ValueError("DCEC route requires a ground deontic predicate fragment")
        return node.operator.value + "(" + _print_ground_dcec(node.formula) + ")"
    if type(node) is not dcec_core.AtomicFormula or not _NAME.fullmatch(node.predicate.name) or not node.arguments:
        raise ValueError("DCEC route requires nonempty ground predicate arguments")
    terms = []
    for argument in node.arguments:
        if (type(argument) is not dcec_core.FunctionTerm or argument.arguments or
                argument.function.argument_sorts or not _NAME.fullmatch(argument.function.name) or
                argument.function.return_sort.name != "Object" or argument.function.return_sort.parent is not None):
            raise ValueError("DCEC route requires ground Object constants")
        terms.append(argument.function.name)
    return node.predicate.name + "(" + ", ".join(terms) + ")"


def prepare_native_fragment(*, family, formula, expected_ast):
    """Check a caller's full native AST against strict original/printed parses.

    This result is a syntax and declared-structure receipt. It is not a learned
    decoder result, a legal-source join, or evidence of cross-family equivalence.
    The returned Lean body still needs an actual native Lake build.
    """
    pins = producer_pins()
    if type(family) is not str or family not in _FAMILIES:
        raise ValueError("unsupported native fragment family")
    if type(formula) is not str or not formula.strip() or len(formula.encode()) > 262144 or type(expected_ast) is not dict:
        raise ValueError("bounded formula and exact supplied native AST required")
    try:
        if len(json.dumps(expected_ast, sort_keys=True, allow_nan=False).encode()) > 524288:
            raise ValueError("supplied native AST exceeds byte bound")
    except (TypeError, RecursionError) as error:
        raise ValueError("bounded JSON native AST required") from error
    syntax = qualification.validate_family_artifact(family, formula)
    if not syntax["passed"]:
        raise ValueError("strict family syntax failed: " + str(syntax["diagnostics"]))
    try:
        if family == "dcec":
            parsed = dcec_integration.parse_dcec_string(formula)
            printed = _print_ground_dcec(parsed)
            reparsed = dcec_integration.parse_dcec_string(printed)
        else:
            parsed = qualification._strict_tdfol(formula)[0]
            printed = parsed.to_string()
            reparsed = qualification._strict_tdfol(printed)[0]
        ast, repeat_ast = modal_projections._ast(parsed), modal_projections._ast(reparsed)
        if ast != expected_ast or ast != repeat_ast:
            raise ValueError("full native AST differs from supplied AST or print/reparse")
        printed_syntax = qualification.validate_family_artifact(family, printed)
        if not printed_syntax["passed"]:
            raise ValueError("printed formula is outside its declared family")
        code, details = emitter.native_modal({"source": formula, "ast": ast}, "dcec" if family == "dcec" else "tdfol")
    except (TypeError, KeyError, IndexError, dcec_integration.DCECParsingError) as error:
        raise ValueError("native fragment cannot be lowered losslessly") from error
    return {"schema": SCHEMA, "family": family, "formula": formula,
        "formula_sha256": hashlib.sha256(formula.encode()).hexdigest(), "native_ast": ast,
        "native_ast_sha256": calendar.digest(ast), "printed": printed,
        "parse_receipt": syntax, "printed_parse_receipt": printed_syntax,
        "exact_native_ast_roundtrip": True, "lean_body": code, "lowering_details": details,
        "producer_pins": pins, "source_bound": False, "source_semantics_verified": False,
        "cross_family_equivalence_verified": False, "backend_executed": False,
        "all_logic_families_supported": False, "admitted": False}


def capability_matrix():
    """Machine-readable routing limits, not inferred equivalence claims."""
    producer_pins()
    return {
        "canonical_legal": {"supported_routes": ["deontic"],
            "scope": "Explicit canonical duration/calendar interpretations; other families require a separately justified translation."},
        "independent_native_fragments": {
            "fol": "Closed one-carrier quantified predicate/Boolean structure; no modalities.",
            "deontic_fol": "Same plus parameterized O/P/F; no temporal operators.",
            "temporal_fol": "Same plus unbounded discrete Nat temporal operators; no deontic operators.",
            "tdfol": "Combined quantified/deontic/unbounded-temporal typed AST; annotations must survive exact parse/print/reparse.",
            "dcec": "Ground Object predicate or O/P/F over it, with strict parser checks and a lossless ground printer."},
        "unsupported_routes": ["calendar_to_FOL_or_LTL_without_clock_translation", "bounded_native_temporal_annotations",
            "multisorted_native_carriers", "free_native_variables", "DCEC_quantified_or_cognitive_or_event_semantics",
            "frame_logic_legal_translation", "transition_system_legal_translation", "higher_order_legal_translation"],
        "source_semantics_verified": False, "all_logic_families_supported": False}
