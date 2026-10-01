"""Source-bound declarations for eight distinct native formula fragments.

These are explicitly supplied formal declarations, not translations inferred
from prose. Parser structure and exact round trips are checked; source meaning,
logical validity, event-calculus axioms and Lean admission are separate gates.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import importlib
import hashlib
from pathlib import Path
import re

from . import family_training as core
from ...ir_core.provenance import SourceRef

_ROUTES = (
    ("FOL", "first_order", "first_order"),
    ("DFOL", "deontic", "deontic_first_order"),
    ("TFOL", "temporal", "temporal_first_order"),
    ("TDFOL", "tdfol", "deontic_temporal_first_order"),
    ("CEC", "event_calculus", "cognitive_event_calculus"),
    ("DCEC", "dcec", "deontic_cognitive_event_calculus"),
    ("frame_logic", "frame_logic", "flogic"),
    ("propositional", "propositional", "propositional"),
)
_EVENTS = {"Happens": 2, "HoldsAt": 2, "Initiates": 3, "Terminates": 3,
           "Releases": 3, "Clipped": 3, "Initially": 1, "ReleasedAt": 2}
_RESERVED = {"G", "K", "B", "I", "O", "P", "F", "X", "U", "S", "W", "R",
             "always", "eventually", "next", "knows", "believes", "intends"}
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def named_logic_routes():
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _SOURCE_SHA:
        raise ValueError("native formula producer changed after import")
    return [dict(requirement_id=r, family_id=f, profile=p) for r, f, p in _ROUTES]


@dataclass(frozen=True)
class NativeFormulaEvidence:
    requirement_id: str
    formula: str
    source_ref: SourceRef

    def __post_init__(self):
        if self.requirement_id not in {r[0] for r in _ROUTES}:
            raise ValueError("unknown named logic fragment")
        if type(self.formula) is not str or not self.formula.strip() or len(self.formula.encode()) > 16384:
            raise ValueError("bounded nonempty native formula required")
        if type(self.source_ref) is not SourceRef:
            raise ValueError("exact native SourceRef required")
        self.source_ref.validate()


def _snapshot(value):
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": value.value}
    if is_dataclass(value):
        return {"node_type": type(value).__name__, **{f.name: _snapshot(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, (tuple, list)):
        return [_snapshot(item) for item in value]
    if type(value) in (str, int, float, bool) or value is None:
        return value
    raise ValueError("unsupported native AST owner: " + type(value).__name__)


def _walk(value):
    pending = [value]
    count = 0
    while pending:
        item = pending.pop()
        count += 1
        if count > 4096:
            raise ValueError("formula exceeds AST size bound")
        if isinstance(item, dict):
            yield item
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _tdfol(text, requirement):
    from ...autoformal.family_qualification import _strict_tdfol
    root, check = _strict_tdfol(text)
    ast = _snapshot(root)
    nodes = list(_walk(ast))
    counts = {"deontic": sum(n.get("node_type") == "DeonticFormula" for n in nodes),
              "temporal": sum(n.get("node_type") in {"TemporalFormula", "BinaryTemporalFormula"} for n in nodes),
              "quantifier": sum(n.get("node_type") == "QuantifiedFormula" for n in nodes),
              "predicate": sum(n.get("node_type") == "Predicate" for n in nodes)}
    for node in nodes:
        if node.get("node_type") in {"Predicate", "FunctionApplication"}:
            name = node.get("name", node.get("function_name"))
            if name in _RESERVED or str(name).casefold() in {r.casefold() for r in _EVENTS}:
                raise ValueError("reserved operator reinterpreted as predicate/function: " + str(name))
    expected = {"FOL": (False, False), "DFOL": (True, False),
                "TFOL": (False, True), "TDFOL": (True, True)}[requirement]
    if (bool(counts["deontic"]), bool(counts["temporal"])) != expected:
        raise ValueError("named fragment lacks its actual operators or contains another fragment")
    if not counts["predicate"]:
        raise ValueError("native predicate required")
    printed = root.to_string()
    replay, _ = _strict_tdfol(printed)
    if _snapshot(replay) != ast:
        raise ValueError("native formula print/parse changed AST")
    return ast, printed, "tdfol_native", counts, [check["parser"].rsplit(".", 1)[0],
        "ipfs_datasets_py.logic.TDFOL.tdfol_core", "ipfs_datasets_py.logic.autoformal.family_qualification"]


def _functional_tree(text):
    """Independently bound the ground functional fragment before native parsing."""
    tokens = re.findall(r"[A-Za-z_]\w*|[(),]|\S", text)
    offset = 0

    def parse(depth=0):
        nonlocal offset
        if depth > 32 or offset >= len(tokens) or not re.fullmatch(r"[A-Za-z_]\w*", tokens[offset]):
            raise ValueError("unsupported cognitive functional syntax")
        name = tokens[offset]; offset += 1
        args = []
        if offset < len(tokens) and tokens[offset] == "(":
            offset += 1
            args.append(parse(depth + 1))
            while offset < len(tokens) and tokens[offset] == ",":
                offset += 1
                args.append(parse(depth + 1))
            if offset >= len(tokens) or tokens[offset] != ")":
                raise ValueError("unbalanced cognitive formula")
            offset += 1
        return name, tuple(args)

    tree = parse()
    if offset != len(tokens):
        raise ValueError("unconsumed cognitive formula input")
    return tree


def _dcec(text, requirement):
    from ...CEC.native import dcec_integration, dcec_core
    expected = _functional_tree(text)
    counts = {"cognitive": 0, "event": 0, "deontic": 0}

    def term(tree):
        name, args = tree
        if args or not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name):
            raise ValueError("cognitive fragment requires explicit ground constant terms")
        return name

    def shape(tree):
        name, args = tree
        if name in {"O", "P", "F"}:
            if len(args) != 1:
                raise ValueError("deontic operator requires one formula")
            counts["deontic"] += 1
            return "deontic", name, shape(args[0])
        if name in {"K", "B", "I"}:
            if len(args) != 2:
                raise ValueError("cognitive operator requires agent and formula")
            counts["cognitive"] += 1
            return "cognitive", name, term(args[0]), shape(args[1])
        if name in {"and", "or", "not", "implies", "iff"}:
            if len(args) != (1 if name == "not" else 2):
                raise ValueError("unsupported connective arity")
            return "connective", name, tuple(shape(arg) for arg in args)
        if name in _RESERVED or name in {"always", "eventually", "next"}:
            raise ValueError("operator outside declared cognitive fragment")
        if name.casefold() in {r.casefold() for r in _EVENTS}:
            if name not in _EVENTS or len(args) != _EVENTS[name]:
                raise ValueError("event-calculus atom spelling/arity mismatch")
            counts["event"] += 1
        if not args:
            raise ValueError("nullary native cognitive predicate is not supported")
        return "predicate", name, tuple(term(arg) for arg in args)

    wanted = shape(expected)
    if not counts["cognitive"] or not counts["event"] or bool(counts["deontic"]) != (requirement == "DCEC"):
        raise ValueError("CEC/DCEC require actual cognition and event atoms with the declared modality")

    def actual_term(node):
        if type(node) is not dcec_core.FunctionTerm or node.arguments or node.function.argument_sorts:
            raise ValueError("native parser changed a ground constant term")
        return node.function.name

    def actual(node):
        if type(node) is dcec_core.DeonticFormula and node.agent is None:
            return "deontic", node.operator.value, actual(node.formula)
        if type(node) is dcec_core.CognitiveFormula:
            return "cognitive", node.operator.value, actual_term(node.agent), actual(node.formula)
        if type(node) is dcec_core.ConnectiveFormula:
            names = {"∧": "and", "∨": "or", "¬": "not", "→": "implies", "↔": "iff"}
            return "connective", names.get(node.connective.value, node.connective.value), tuple(actual(f) for f in node.formulas)
        if type(node) is dcec_core.AtomicFormula:
            return "predicate", node.predicate.name, tuple(actual_term(arg) for arg in node.arguments)
        raise ValueError("native cognitive parser returned unsupported AST")

    def render(tree):
        name, args = tree
        return name + ("(" + ",".join(render(a) for a in args) + ")" if args else "")

    root = dcec_integration.parse_dcec_string(text)
    if actual(root) != wanted:
        raise ValueError("native cognitive parser changed operator/term structure")
    printed = render(expected)
    replay = dcec_integration.parse_dcec_string(printed)
    ast = _snapshot(root)
    if _snapshot(replay) != ast:
        raise ValueError("native cognitive reparse changed AST")
    return ast, printed, "dcec_native", counts, [dcec_integration.__name__, dcec_core.__name__,
        "ipfs_datasets_py.logic.CEC.native.dcec_cleaning", "ipfs_datasets_py.logic.CEC.native.dcec_parsing",
        "ipfs_datasets_py.logic.CEC.native.dcec_prototypes"]


def prepare_native_formula_evidence(item, expected_source_ref):
    """Strictly parse a source-bound declaration and return an inert target.

    Exact source binding does not establish that the declaration faithfully
    translates that source. No learned-decoder or theorem evidence is implied.
    """
    if type(item) is not NativeFormulaEvidence or type(expected_source_ref) is not SourceRef:
        raise ValueError("NativeFormulaEvidence and native source reference required")
    if item.source_ref.to_dict() != expected_source_ref.to_dict():
        raise ValueError("formula SourceRef differs from exact domain source")
    route = next(row for row in named_logic_routes() if row["requirement_id"] == item.requirement_id)
    if item.requirement_id in {"FOL", "DFOL", "TFOL", "TDFOL"}:
        ast, printed, fmt, counts, modules = _tdfol(item.formula, item.requirement_id)
    elif item.requirement_id in {"CEC", "DCEC"}:
        ast, printed, fmt, counts, modules = _dcec(item.formula, item.requirement_id)
    elif item.requirement_id == "frame_logic":
        from ...parsers import flogic
        parsed = flogic.parse_flogic(item.formula)
        if not parsed.ok or parsed.diagnostics or parsed.document is None or parsed.document.unsupported:
            raise ValueError("strict native F-logic parse failed")
        printed = flogic.print_flogic(parsed.document)
        replay = flogic.parse_flogic(printed)
        if not replay.ok or replay.diagnostics or not flogic.documents_semantically_compatible(parsed.document, replay.document):
            raise ValueError("native frame print/parse changed declaration")
        ast = replay.document.to_dict()
        fmt, counts, modules = "flogic_native", {"statement": len(replay.document.statements)}, [flogic.__name__]
    else:
        from ...parsers import modal
        from ...syntax_core.algebra import alpha_equivalent
        from ...autoformal.family_qualification import _strict_propositional
        _strict_propositional(item.formula)
        parsed = modal.parse_modal(item.formula, modal.profile_k())
        printed = parsed.printed
        replay = modal.parse_modal(printed, modal.profile_k())
        if not replay.ok or replay.diagnostics or not alpha_equivalent(parsed.root, replay.root):
            raise ValueError("native propositional print/parse failed")
        # Source offsets/node identities differ after printing. Compare the
        # native canonical printer after a second strict parse, not those IDs.
        _strict_propositional(printed)
        if replay.printed != printed:
            raise ValueError("native propositional print/parse is not stable")
        ast = replay.root.to_dict()
        fmt, counts, modules = "shared_logic", {"propositional": 1}, [modal.__name__,
            "ipfs_datasets_py.logic.syntax_core.algebra", "ipfs_datasets_py.logic.syntax_core.ast",
            "ipfs_datasets_py.logic.autoformal.family_qualification"]
    pins = {}
    from ....optimizers.logic_theorem_optimizer.autoencoder_schema_lake import _pin_imported_module
    for name in [__name__, "ipfs_datasets_py.logic.ir_core.provenance", *modules]:
        module = importlib.import_module(name)
        pins[name] = _pin_imported_module(module)
    return {"logic_family": route["family_id"], "profile": route["profile"],
        "payload": {"requirement_id": item.requirement_id, "formula": item.formula, "printed": printed,
                    "native_ast": ast, "ast_format": fmt, "operator_counts": counts,
                    "source_ref": item.source_ref.to_dict(), "source_meaning_verified": False},
        "validation": {"native_parse_passed": True, "native_structure_checked": True, "native_reparse_passed": True},
        "producer_pins": pins,
        "qualification_gaps": ["source_formula_fidelity_not_verified", "external_proofs_not_run",
            "native_syntax_does_not_establish_modal_or_event_calculus_axioms"]}


__all__ = ["NativeFormulaEvidence", "named_logic_routes", "prepare_native_formula_evidence"]
