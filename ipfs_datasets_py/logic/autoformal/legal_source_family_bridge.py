"""Direct source spans to bounded native legal-family ASTs.

This is a structural compiler under an explicit caller interpretation, not an
extractor or a legal-fidelity oracle.  Every canonical facet has an occurrence
binding; every qualifier has a typed expression.  O/P/F remain distinct modal
parameters with no agent or context annotation.  This *new* null-context profile
is not asserted equivalent to the existing explicit-clock/calendar gate.

TDFOL here covers its ground, non-temporal deontic subset.  DCEC is restricted to
ground, qualifier-free O/P/F.  Unsupported temporal facets and families fail
closed rather than becoming opaque predicates or losing normative force.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from . import legal_family_routes as routes
from ..TDFOL import tdfol_core as t
from ..CEC.native import dcec_core as d
from ..intent_ir.formalize.modal_projections import _ast
from ..legal_ir.canonical_contracts import CanonicalRoundTripIR
from ..formalization.autoencoder import native_legal_qualified_lean as qualified

SCHEMA = "legal-source-family-bridge/v1"
INTERPRETATION_SCHEMA = "legal-source-family-interpretation/v1"
PROFILE = "ground-null-context/v1"
DECLARATION_SCOPE = "caller_supplied_interpretation_not_source_translation"
ACTIVATION_SCOPE = "all_conditions_at_evaluation_time"
EXCEPTION_SCOPE = "any_exception_waives_at_evaluation_time"
SUPPORTED_FAMILIES = ("deontic_fol", "tdfol", "dcec")
CANONICAL_FAMILIES = {"deontic_fol": "deontic", "tdfol": "tdfol", "dcec": "dcec"}
MAX_SOURCE_BYTES = 1_000_000
MAX_INPUT_BYTES = 2_000_000
MAX_REPORT_BYTES = 32_000_000
MAX_RULES = 64
MAX_OCCURRENCES = 128
_FACETS = {"modality", "actor", "action", "object", "conditions", "exceptions", "temporal"}
_KNOWN_TIME_LITERAL = re.compile(
    r"(?:(?:within|for at least) [0-9]+ (?:days?|hours?)|before [0-9]{4}-[0-9]{2}-[0-9]{2}|always|eventually)",
    re.IGNORECASE)
_FALSE = {key: False for key in (
    "source_semantics_verified", "cross_family_equivalence_verified",
    "old_calendar_gate_equivalence_verified", "backend_executed", "proof_authority",
    "admitted", "formalized", "all_logic_families_supported")}


def _wire(value, *, bound=MAX_REPORT_BYTES):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ValueError("bounded inert JSON required") from error
    if len(raw) > bound:
        raise ValueError("JSON byte bound exceeded")
    return raw


def digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _closed(value, fields, label):
    _require(type(value) is dict and set(value) == set(fields), "closed " + label + " required")


def _text(value, label):
    _require(type(value) is str and bool(value.strip()) and len(value.encode("utf-8")) <= 4096,
             "bounded nonblank " + label + " required")
    return value


def _pins():
    return routes.producer_pins() | {
        str(Path(qualified.__file__).resolve()): hashlib.sha256(Path(qualified.__file__).read_bytes()).hexdigest(),
        str(Path(__file__).resolve()): hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


_IMPORTED_PINS = _pins()


def producer_pins():
    _require(_pins() == _IMPORTED_PINS, "source family bridge producer changed since import")
    return dict(_IMPORTED_PINS)


def _candidate(value):
    _wire(value, bound=MAX_INPUT_BYTES)
    _closed(value, {"candidate_id", "source_text", "source_sha256", "canonical_ir"}, "candidate")
    _text(value["candidate_id"], "candidate identity")
    source = value["source_text"]
    _require(type(source) is str and source.strip() and len(source.encode("utf-8")) <= MAX_SOURCE_BYTES,
             "bounded complete source required")
    _require(hashlib.sha256(source.encode("utf-8")).hexdigest() == value["source_sha256"],
             "complete source SHA256 differs")
    ir = value["canonical_ir"]
    _closed(ir, {"rules"}, "canonical IR")
    _require(type(ir["rules"]) is list and 0 < len(ir["rules"]) <= MAX_RULES, "bounded canonical rule list required")
    for rule in ir["rules"]:
        _closed(rule, _FACETS, "canonical rule")
        for facet in ("conditions", "exceptions", "temporal"):
            _require(type(rule[facet]) is list and len(rule[facet]) <= 16, "bounded qualifier list required")
            for literal in rule[facet]:
                _text(literal, "qualifier literal")
                _require(facet == "temporal" or not _KNOWN_TIME_LITERAL.fullmatch(literal),
                         "recognized temporal literal cannot become an opaque activation or exception predicate")
        _require(not rule["temporal"], "temporal and calendar qualifiers require another explicit profile")
        for facet in ("actor", "action"):
            _text(rule[facet], facet)
        _require(type(rule["object"]) is str and len(rule["object"].encode("utf-8")) <= 4096,
                 "bounded object string required")
    _require(CanonicalRoundTripIR.from_dict(ir).to_dict() == ir, "canonical ordering or facet values differ")
    return json.loads(_wire(value))


def interpretation_skeleton(candidate):
    """Bind an unfilled interpretation to a candidate; None fields cannot compile."""
    producer_pins()
    candidate = _candidate(candidate)
    return {"schema": INTERPRETATION_SCHEMA, "profile": PROFILE,
        "candidate_sha256": digest(candidate), "source_sha256": candidate["source_sha256"],
        "canonical_ir_sha256": digest(candidate["canonical_ir"]), "declaration_scope": DECLARATION_SCOPE,
        "modal_context": None, "activation_scope": None, "exception_scope": None,
        "rules": [{"rule_index": index,
            "conditions": [{"literal": literal, "expression": None} for literal in rule["conditions"]],
            "exceptions": [{"literal": literal, "expression": None} for literal in rule["exceptions"]]}
            for index, rule in enumerate(candidate["canonical_ir"]["rules"])]}


def _interpretation(value, candidate):
    _wire(value, bound=MAX_INPUT_BYTES)
    skeleton = interpretation_skeleton(candidate)
    _closed(value, skeleton, "source interpretation")
    for field in set(skeleton) - {"activation_scope", "exception_scope", "rules"}:
        _require(value[field] == skeleton[field], "interpretation identity, profile or modal context differs")
    _require(value["activation_scope"] == ACTIVATION_SCOPE and value["exception_scope"] == EXCEPTION_SCOPE,
             "explicit activation and exception scopes required")
    _require(type(value["rules"]) is list and len(value["rules"]) == len(skeleton["rules"]),
             "complete ordered qualifier interpretations required")
    literals = {}
    for row, expected in zip(value["rules"], skeleton["rules"]):
        _closed(row, expected, "rule interpretation")
        _require(type(row["rule_index"]) is int and row["rule_index"] == expected["rule_index"],
                 "ordered rule interpretation index differs")
        for facet in ("conditions", "exceptions"):
            _require(type(row[facet]) is list and len(row[facet]) == len(expected[facet]),
                     "complete qualifier interpretation coverage required")
            for binding, placeholder in zip(row[facet], expected[facet]):
                _closed(binding, {"literal", "expression"}, "qualifier interpretation")
                _require(binding["literal"] == placeholder["literal"], "ordered qualifier literal differs")
                # Reuse the existing closed typed Boolean/predicate contract.
                qualified._expression(binding["expression"], "t")
                literal = binding["literal"]
                _require(literal not in literals or literals[literal] == binding["expression"],
                         "same qualifier literal has conflicting interpretations")
                literals[literal] = binding["expression"]
    return json.loads(_wire(value))


def _span(value, source, start, end, canonical_value, *, modality=False):
    _closed(value, {"start_char", "end_char", "source_text", "canonical_value"}, "facet span")
    left, right = value["start_char"], value["end_char"]
    _require(type(left) is int and type(right) is int and start <= left < right <= end,
             "facet span must lie inside its source occurrence")
    _require(source[left:right] == value["source_text"] and value["canonical_value"] == canonical_value,
             "exact facet source slice or canonical value differs")
    _text(value["source_text"], "facet surface")
    _require(modality or value["source_text"] == canonical_value,
             "direct-span profile cannot infer or normalize a canonical facet")


def _occurrences(values, candidate):
    _wire(values, bound=MAX_INPUT_BYTES)
    _require(type(values) is list and 0 < len(values) <= MAX_OCCURRENCES, "bounded ordered occurrences required")
    source, rules = candidate["source_text"], candidate["canonical_ir"]["rules"]
    seen, covered, previous_end = set(), set(), 0
    for row in values:
        _closed(row, {"occurrence_id", "rule_index", "start_char", "end_char", "source_text", "facets"}, "occurrence")
        identity = _text(row["occurrence_id"], "occurrence identity")
        _require(identity not in seen, "duplicate occurrence identity")
        seen.add(identity)
        index, start, end = row["rule_index"], row["start_char"], row["end_char"]
        _require(type(index) is int and 0 <= index < len(rules), "known exact rule index required")
        _require(type(start) is int and type(end) is int and previous_end <= start < end <= len(source),
                 "ordered nonoverlapping source occurrences required")
        _require(source[start:end] == row["source_text"], "complete occurrence source slice differs")
        previous_end = end
        covered.add(index)
        rule, facets = rules[index], row["facets"]
        _closed(facets, _FACETS, "occurrence facets")
        for facet in ("modality", "actor", "action", "object"):
            if facet == "object" and not rule[facet]:
                _require(facets[facet] is None, "absent object must have no source span")
            else:
                _span(facets[facet], source, start, end, rule[facet], modality=facet == "modality")
        for facet in ("conditions", "exceptions", "temporal"):
            _require(type(facets[facet]) is list and len(facets[facet]) == len(rule[facet]),
                     "complete ordered qualifier source spans required")
            for value, literal in zip(facets[facet], rule[facet]):
                _span(value, source, start, end, literal)
    _require(covered == set(range(len(rules))), "every canonical rule needs a source occurrence")
    return json.loads(_wire(values))


class _Symbols:
    def __init__(self, family):
        self.family, self.rows = family, {}

    def bind(self, kind, value, arity=None):
        payload = {"kind": kind, "value": value}
        if kind == "predicate":
            payload["arity"] = arity
        identifier = digest(payload)
        symbol = ("entity:" if kind == "constant" and self.family != "dcec" else "S") + identifier
        row = payload | {"symbol": symbol}
        _require(symbol not in self.rows or self.rows[symbol] == row, "symbol collision")
        self.rows[symbol] = row
        return symbol

    def predicate(self, name, arguments):
        symbol = self.bind("predicate", name, len(arguments))
        terms = [self.bind("constant", arg) for arg in arguments]
        if self.family == "dcec":
            sort = d.Sort("Object")
            return d.AtomicFormula(d.Predicate(symbol, [sort] * len(terms)),
                [d.FunctionTerm(d.Function(term, [], sort), []) for term in terms])
        return t.Predicate(symbol, tuple(t.Constant(term) for term in terms))


def _combine(operator, values):
    _require(bool(values), "nonempty Boolean combination required")
    result = values[0]
    for value in values[1:]:
        result = t.BinaryFormula(operator, result, value)
    return result


def _expression(value, symbols):
    op = value["op"]
    if op == "atom":
        return symbols.predicate(value["predicate"]["name"], value["predicate"]["arguments"])
    if op == "not":
        return t.UnaryFormula(t.LogicOperator.NOT, _expression(value["operand"], symbols))
    return _combine(t.LogicOperator.AND if op == "all" else t.LogicOperator.OR,
                    [_expression(child, symbols) for child in value["operands"]])


def _formula(rule, interpretation, symbols):
    arguments = [rule["actor"]] + ([rule["object"]] if rule["object"] else [])
    atom = symbols.predicate(rule["action"], arguments)
    if symbols.family == "dcec":
        _require(not rule["conditions"] and not rule["exceptions"],
                 "DCEC profile supports only qualifier-free ground O/P/F")
        return d.DeonticFormula(d.DeonticOperator(rule["modality"]), atom)
    norm = t.DeonticFormula(t.DeonticOperator(rule["modality"]), atom, agent=None, context=None)
    guards = [_expression(row["expression"], symbols) for row in interpretation["conditions"]]
    exceptions = [_expression(row["expression"], symbols) for row in interpretation["exceptions"]]
    if exceptions:
        guards.append(t.UnaryFormula(t.LogicOperator.NOT, _combine(t.LogicOperator.OR, exceptions)))
    return (t.BinaryFormula(t.LogicOperator.IMPLIES, _combine(t.LogicOperator.AND, guards), norm)
            if guards else norm)


def _decode_core(ast, family, symbols):
    """Invert the actual native modal/predicate spine, not a copy of the input."""
    node = ast
    if node.get("node_type") == "BinaryFormula":
        _require(node["operator"]["value"] == "→", "native activation guard must imply the complete norm")
        node = node["right"]
    _require(node.get("node_type") == "DeonticFormula" and node.get("agent") is None
             and node.get("context") is None, "ground null-context native norm required")
    modality = node["operator"]["value"]
    _require(modality in {"O", "P", "F"}, "normative force must survive inversion")
    atom = node["formula"]
    _require(atom.get("node_type") == ("AtomicFormula" if family == "dcec" else "Predicate"),
             "native norm body must preserve the action atom")
    name = atom["predicate"]["name"] if family == "dcec" else atom["name"]
    predicate = symbols[name]
    _require(predicate["kind"] == "predicate" and predicate["arity"] == len(atom["arguments"]),
             "native predicate signature differs")
    arguments = []
    for argument in atom["arguments"]:
        if family == "dcec":
            _require(argument["node_type"] == "FunctionTerm" and not argument["arguments"],
                     "ground native DCEC constant required")
            symbol = argument["function"]["name"]
        else:
            _require(argument["node_type"] == "Constant", "ground native TDFOL constant required")
            symbol = argument["name"]
        _require(symbols[symbol]["kind"] == "constant", "constant symbol ledger differs")
        arguments.append(symbols[symbol]["value"])
    _require(len(arguments) in {1, 2}, "native legal predicate arity differs")
    return {"modality": modality, "actor": arguments[0], "action": predicate["value"],
            "object": arguments[1] if len(arguments) == 2 else ""}


def prepare_source_family(candidate, interpretation, occurrence_bindings, *, family):
    """Compile explicitly interpreted source-bound rules to an actual native AST.

    The source cue for a modality and the supplied qualifier expression are
    declarations.  Their legal meaning is not established by matching bytes.
    """
    pins = producer_pins()
    _require(type(family) is str and family in SUPPORTED_FAMILIES,
             "unsupported family; normative force cannot be erased for FOL or temporal-only output")
    candidate = _candidate(candidate)
    interpretation = _interpretation(interpretation, candidate)
    occurrences = _occurrences(occurrence_bindings, candidate)
    symbols, formulas, bodies, reconstructed = _Symbols(family), [], [], {}
    rules = candidate["canonical_ir"]["rules"]
    for position, occurrence in enumerate(occurrences):
        index = occurrence["rule_index"]
        rule, declaration = rules[index], interpretation["rules"][index]
        typed = _formula(rule, declaration, symbols)
        concrete = routes._print_ground_dcec(typed) if family == "dcec" else typed.to_string()
        native = routes.prepare_native_fragment(family=family, formula=concrete, expected_ast=_ast(typed))
        # The native printer/reparser must retain exactly the constructed scope,
        # not merely accept another syntactically valid formula.
        core = _decode_core(native["native_ast"], family, symbols.rows)
        inverse = core | {facet: [row["literal"] for row in declaration[facet]]
                          for facet in ("conditions", "exceptions")} | {"temporal": []}
        _require(inverse == rule, "native AST and qualifier ledger fail canonical inversion")
        _require(index not in reconstructed or reconstructed[index] == inverse,
                 "repeated rule occurrences reconstructed differently")
        reconstructed[index] = inverse
        formulas.append({"occurrence_id": occurrence["occurrence_id"], "rule_index": index,
            "occurrence_sha256": digest(occurrence), "canonical_rule_sha256": digest(rule),
            "interpretation_sha256": digest(declaration), "formula": concrete,
            "native_ast": native["native_ast"], "native_ast_sha256": digest(native["native_ast"]),
            "native_receipt": native})
        bodies.append(f"namespace Occurrence{position:04d}\n" + native["lean_body"] +
                      f"\nend Occurrence{position:04d}\n")
    canonical = {"rules": [reconstructed[index] for index in range(len(rules))]}
    _require(canonical == candidate["canonical_ir"], "complete canonical reconstruction differs")
    report = {"schema": SCHEMA, "profile": PROFILE, "family": family,
        "logic_family": CANONICAL_FAMILIES[family], "native_parser_profile": family,
        "candidate_id": candidate["candidate_id"], "candidate_sha256": digest(candidate),
        "source_sha256": candidate["source_sha256"], "canonical_ir_sha256": digest(candidate["canonical_ir"]),
        "interpretation_sha256": digest(interpretation), "interpretation": interpretation,
        "occurrence_bindings_sha256": digest(occurrences), "occurrence_bindings": occurrences,
        "symbol_table": [symbols.rows[name] for name in sorted(symbols.rows)], "formulas": formulas,
        "canonical_roundtrip": canonical, "canonical_roundtrip_exact": True,
        "canonical_inversion_scope": "native modal/action/argument spine plus complete ordered qualifier literal ledger; exact full native AST checked",
        "source_bound": True, "direct_facet_spans_validated": True,
        "qualifier_structure_scope": "explicit caller expressions; all conditions outside modal, any exception waives",
        "declaration_scope": DECLARATION_SCOPE, "modal_context": None,
        "native_profile_scope": ("ground qualifier-free deontic Object fragment" if family == "dcec"
                                 else "ground Boolean/deontic fragment; no temporal operators or quantifiers"),
        "lean_body": "\n".join(bodies), "producer_pins": pins,
        "limitations": ["Source identity and facet spans do not establish correct legal interpretation.",
            "Modality cues and qualifier meanings are caller declarations, not verified natural-language semantics.",
            "O/P/F are independent interpretation parameters; no modal axioms or normative truth are asserted.",
            "TDFOL support here is its non-temporal ground deontic subset.",
            "DCEC constants are native zero-arity Object functions; no cross-family interpretation equivalence is asserted.",
            "No equivalence to the existing explicit-clock or calendar gate is asserted.",
            "Compilation requires an actual subsequent lake build legal; this preparation never executes a backend."],
        **_FALSE}
    report["report_sha256"] = digest(report)
    _wire(report)
    _require(producer_pins() == pins, "producer changed during source bridge compilation")
    return json.loads(_wire(report))


def validate_source_family(report, *, candidate, interpretation, occurrence_bindings, family):
    """Regenerate from authoritative inputs; repaired report hashes confer nothing."""
    _wire(report)
    expected = prepare_source_family(candidate, interpretation, occurrence_bindings, family=family)
    _require(_wire(report) == _wire(expected), "source family report differs from authoritative regeneration")
    return True


__all__ = ["prepare_source_family", "validate_source_family", "interpretation_skeleton",
           "producer_pins", "digest", "SCHEMA", "PROFILE", "SUPPORTED_FAMILIES"]
