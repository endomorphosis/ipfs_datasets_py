"""Fail-closed syntax checks for exact, source-bound legal family exports.

This is a syntax gate, not a prover or an equivalence test. It deliberately
does not use ``family_supervision``'s stitch fixtures or replace malformed
exports with convenient formulas. A caller must separately verify that the
canonical rule came from its exact input, and perform semantic and Lake gates.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

REQUIRED_FAMILIES = (
    "fol", "deontic_fol", "temporal_fol", "deontic_temporal_fol",
    "deontic_cognitive_event_calculus", "frame_logic",
)
_ALIASES = {
    "first_order_logic": "fol", "deontic": "deontic_fol", "tfol": "temporal_fol",
    "tdfol": "deontic_temporal_fol", "temporal_deontic_fol": "deontic_temporal_fol",
    "cec": "deontic_cognitive_event_calculus", "dcec": "deontic_cognitive_event_calculus",
    "deontic_cec": "deontic_cognitive_event_calculus", "flogic": "frame_logic",
}
_TARGETS = {
    "fol": "fol", "deontic_fol": "deontic_fol", "temporal_fol": "temporal_fol",
    "deontic_temporal_fol": "deontic_temporal_fol",
    "deontic_cognitive_event_calculus": "deontic_cec", "frame_logic": "frame_logic",
}
MAX_ARTIFACT_BYTES = 262_144


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _module(name: str) -> Any:
    """Every parser/exporter must resolve in the canonical workspace tree."""
    from .tree_pin import LogicTreePinError, workspace_root
    module = importlib.import_module(name)
    path = Path(getattr(module, "__file__", "")).resolve()
    if not path.is_file() or workspace_root() not in path.parents:
        raise LogicTreePinError(f"Family qualification resolved outside workspace: {name}={path}")
    return module


def _strict_tdfol(formula: str) -> tuple[Any, dict[str, Any]]:
    module = _module("ipfs_datasets_py.logic.TDFOL.tdfol_parser")
    tokens = module.TDFOLLexer(formula).tokenize()
    # The legacy lexer skips unknown characters. Its parser alone is therefore
    # insufficient: require complete character coverage before parsing.
    cursor = 0
    for token in tokens:
        if formula[cursor:token.position].strip():
            raise ValueError(f"unconsumed lexical input at offset {cursor}")
        if token.type != module.TokenType.EOF:
            if formula[token.position:token.position + len(token.value)] != token.value:
                raise ValueError(f"token/source mismatch at offset {token.position}")
            cursor = token.position + len(token.value)
    if formula[cursor:].strip():
        raise ValueError(f"unconsumed lexical suffix at offset {cursor}")
    root = module.TDFOLParser(tokens).parse()  # Requires EOF.
    classes: set[str] = set()
    predicates: set[str] = set()
    pending = [root]
    while pending:
        node = pending.pop()
        classes.add(type(node).__name__)
        if type(node).__name__ == "Predicate":
            predicates.add(str(node.name))
        for name in ("formula", "left", "right"):
            child = getattr(node, name, None)
            if child is not None:
                pending.append(child)
    if "legacy_deontic_target" in predicates:
        raise ValueError("legacy deontic target compatibility fallback is not a strict formula")
    return root, {
        "parser": module.__name__ + ".TDFOLParser",
        "parser_source_sha256": hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest(),
        "consumed_all_input": True, "ast_classes": sorted(classes),
        "predicates": sorted(predicates), "printed": root.to_string(),
    }


def _dcec_fragment_shape(node: Any, *, shared: bool, term: bool = False) -> Any:
    """Compare two independent parsers on the qualified normative fragment.

    The shared legacy parser accepts both infix and s-expressions; some
    parenthesized infix strings can otherwise be reinterpreted as predicates
    with Boolean arguments. Preserve operator, argument, and term structure.
    The parsers call bare unbound terms variables/constants respectively, so
    compare those lexical atoms without claiming signature/type equivalence.
    """
    kind = str(node.kind.value) if shared else type(node).__name__
    if term:
        if kind in {"constant", "variable", "Constant", "Variable"}:
            name = (str(node.metadata.get("literal", node.symbol)) if shared else node.name)
            return ("atom", name)
        if kind in {"application", "FunctionApplication"}:
            name = node.symbol if shared else node.function_name
            return ("function", name, tuple(_dcec_fragment_shape(child, shared=shared, term=True)
                                             for child in node.arguments))
        raise ValueError(f"dcec_boolean_used_as_term:{kind}")
    if kind in {"predicate", "Predicate"}:
        name = node.symbol if shared else node.name
        return ("predicate", name, tuple(_dcec_fragment_shape(child, shared=shared, term=True)
                                          for child in node.arguments))
    if kind in {"forall", "exists", "QuantifiedFormula"}:
        if shared:
            result = _dcec_fragment_shape(node.arguments[0], shared=True)
            for binder in reversed(node.binders):
                result = (kind, binder.name, result)
            return result
        return (node.quantifier.name.lower(), node.variable.name,
                _dcec_fragment_shape(node.formula, shared=False))
    if kind == "DeonticFormula":
        return ("deontic", node.operator.value, _dcec_fragment_shape(node.formula, shared=False))
    if kind == "extension":
        extension = node.extension
        if extension.payload_schema == "legacy.deontic/v1" and len(extension.children) == 1:
            return ("deontic", extension.payload["letter"],
                    _dcec_fragment_shape(extension.children[0], shared=True))
        # Actual EC atoms have fixed arities. The syntax-only TDFOL parser
        # treats them as predicates, so preserve their published surface name.
        event_atoms = {"happens": ("Happens", 2), "holds_at": ("HoldsAt", 2),
                       "initiates": ("Initiates", 3), "terminates": ("Terminates", 3),
                       "releases": ("Releases", 3)}
        event = event_atoms.get(str(extension.payload.get("kind")))
        if extension.payload_schema == "event_calculus.atom/v1" and event is not None:
            if len(extension.children) != event[1]:
                raise ValueError("dcec_event_atom_arity_mismatch")
            return ("predicate", event[0], tuple(_dcec_fragment_shape(child, shared=True, term=True)
                                                 for child in extension.children))
        raise ValueError("dcec_operator_outside_qualified_fragment")
    if not shared and kind in {"BinaryFormula", "UnaryFormula"}:
        operator = node.operator.name.lower()
        children = [node.left, node.right] if kind == "BinaryFormula" else [node.formula]
    elif shared and kind in {"and", "or", "not", "implies", "iff", "xor"}:
        operator, children = kind, node.arguments
    else:
        raise ValueError(f"dcec_node_outside_qualified_fragment:{kind}")
    shapes = [_dcec_fragment_shape(child, shared=shared) for child in children]
    if operator in {"and", "or"}:
        # Native TDFOL nests binary conjunction; shared AST stores n-ary form.
        shapes = [item for shape in shapes for item in (shape[1] if shape[0] == operator else (shape,))]
    return (operator, tuple(shapes))


def validate_family_artifact(family: str, formula: str) -> dict[str, Any]:
    """Parse one *unaltered* emitted artifact; success is syntax evidence only.

    This lower-level helper cannot qualify a source/model on its own because it
    does not bind a formula to a producer, rule, checkpoint, or legal text.
    """
    family = _ALIASES.get(family, family)
    result: dict[str, Any] = {
        "family": family, "passed": False, "syntax_valid": False,
        "formula": formula, "formula_sha256": _text_digest(formula),
        "diagnostics": [], "semantic_equivalence_checked": False,
        "source_bound": False, "admitted": False, "formalized": False,
    }
    try:
        if family not in REQUIRED_FAMILIES:
            raise ValueError("unsupported_family")
        if not formula.strip():
            raise ValueError("empty_artifact")
        if len(formula.encode()) > MAX_ARTIFACT_BYTES:
            raise ValueError("artifact_size_limit")
        if "stitch:" in formula or "??" in formula:
            raise ValueError("placeholder_artifact")
        if family == "frame_logic":
            module = _module("ipfs_datasets_py.logic.parsers.flogic")
            parsed = module.parse_flogic(formula)
            result["parser"] = module.__name__ + ".parse_flogic"
            result["parser_source_sha256"] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            result["diagnostics"] = [row.to_dict() for row in parsed.diagnostics]
            # Unsupported constructs may be warnings while result.ok is true.
            if not parsed.ok or parsed.diagnostics:
                raise ValueError("strict_frame_parse_failed")
            result["printed"] = parsed.printed
        elif family == "deontic_cognitive_event_calculus":
            # The older native DCEC parser can turn malformed quantified
            # input into a conjunction of tokens. The shared importer rejects
            # unknown/trailing input. Disable its EC-first path, which treats
            # O(...) as an ordinary predicate rather than a deontic operator.
            module = _module("ipfs_datasets_py.logic.parsers.legacy_modal")
            profile = replace(module.profile_dcec(), admit_event_calculus=False)
            parsed = module.LegacyLogicImporter(dcec=profile).import_text(formula, family="dcec")
            result["parser"] = module.__name__ + ".LegacyLogicImporter[dcec]"
            result["parser_source_sha256"] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            result["diagnostics"] = [row.to_dict() for row in parsed.diagnostics]
            receipt = parsed.receipt
            result["parse_receipt"] = receipt.to_dict() if receipt else None
            if not parsed.ok or parsed.diagnostics or receipt is None or receipt.losses:
                raise ValueError("strict_dcec_parse_failed")
            independent, independent_receipt = _strict_tdfol(formula)
            expected_shape = _dcec_fragment_shape(independent, shared=False)
            actual_shape = _dcec_fragment_shape(parsed.root, shared=True)
            result["qualified_fragment"] = "deontic_first_order_and_event_atoms"
            result["independent_parser"] = independent_receipt
            result["parser_ast_parity"] = expected_shape == actual_shape
            if expected_shape != actual_shape:
                raise ValueError("dcec_parser_ast_disagreement")
            result["normalized_syntax_shape_sha256"] = _digest(expected_shape)
            result["printed"] = parsed.printed
        else:
            _, parsed = _strict_tdfol(formula)
            result.update(parsed)
            classes = set(parsed["ast_classes"])
            deontic = "DeonticFormula" in classes
            temporal = bool(classes & {"TemporalFormula", "BinaryTemporalFormula"})
            if family == "fol" and (deontic or temporal):
                raise ValueError("modal_operator_outside_fol")
            if family == "deontic_fol" and temporal:
                raise ValueError("temporal_operator_outside_deontic_fol")
            if family == "temporal_fol" and deontic:
                raise ValueError("deontic_operator_outside_temporal_fol")
        result.update(passed=True, syntax_valid=True, consumed_all_input=True)
    except Exception as exc:
        from .tree_pin import LogicTreePinError
        if isinstance(exc, LogicTreePinError):
            raise
        result["diagnostics"].append({"code": str(exc), "exception": type(exc).__name__})
    return result


def export_canonical_rule_families(
    rule: Mapping[str, Any], *, source_id: str,
    temporal_records: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Serialize a compiled canonical rule in the supported family fragments.

    Identifiers encode actual compiler-supplied atoms, never missing slots.
    Their reversible binding table and the original rule accompany each
    artifact. FOL/TFOL omit the deontic operator and explicitly say so. DCEC
    uses its deontic predicate fragment: no fictitious event or time point is
    introduced. Temporal atoms retain their exact text; parser-supplied kinds
    and quantities are included as typed predicates when present. No new
    temporal interpretation is inferred from natural language here.
    """
    contracts = _module("ipfs_datasets_py.logic.legal_ir.canonical_contracts")
    canonical = contracts.CanonicalRule.from_dict(rule).to_dict()
    temporal_indices = {value: index for index, value in enumerate(canonical["temporal"])}
    bindings: dict[str, dict[str, str]] = {}

    def symbol(slot: str, value: str) -> str:
        if not value.strip() or "stitch:" in value:
            raise ValueError(f"missing_or_placeholder_atom:{slot}")
        stem = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:48]
        identifier = f"{slot}_{stem}_{_text_digest(value)[:12]}"
        bindings[identifier] = {"slot": slot, "value": value}
        return identifier

    actor = symbol("actor", canonical["actor"])
    action = symbol("action", canonical["action"])
    arguments = [actor]
    if canonical["object"]:
        arguments.append(symbol("object", canonical["object"]))
    action_atom = f"{action}({','.join(arguments)})"
    temporal_atoms: list[str] = []
    for value in canonical["temporal"]:
        temporal_atoms.append(f"{symbol('temporal', value)}({','.join(arguments)})")
    accepted_records: list[dict[str, Any]] = []
    for record in temporal_records:
        value = str(record.get("value") or "")
        kind = str(record.get("temporal_kind") or "")
        quantity = record.get("quantity")
        # Sidecars can enrich only an exact existing canonical temporal atom.
        # within_duration is kept distinct from minimum_duration. Neither is
        # transformed into an invented Always/Eventually/time-bound operator.
        canonical_value = value
        if kind == "within_duration" and f"within {value}" in canonical["temporal"]:
            canonical_value = f"within {value}"
        if canonical_value not in temporal_indices:
            raise ValueError("temporal_sidecar_not_bound_to_canonical_atom")
        if kind not in {"minimum_duration", "within_duration"}:
            continue
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise ValueError("duration_quantity_missing_or_invalid")
        temporal_atoms.append(f"{kind}({action_atom},{quantity},{symbol('duration', value)})")
        accepted_records.append({**record, "canonical_temporal_atom": canonical_value,
                                 "canonical_temporal_index": temporal_indices[canonical_value]})

    def conjunction(parts: Sequence[str]) -> str:
        if not parts:
            raise ValueError("empty_formula_parts")
        return parts[0] if len(parts) == 1 else "(" + " and ".join(parts) + ")"

    body = conjunction([action_atom, *temporal_atoms])
    guards = [f"{symbol('condition', value)}({','.join(arguments)})" for value in canonical["conditions"]]
    guards.extend(f"not {symbol('exception', value)}({','.join(arguments)})" for value in canonical["exceptions"])
    # Conjunction binds tighter than implication in both strict parsers. Do
    # not wrap a leading `not ...` in parentheses: DCEC reserves that opening
    # for s-expressions and would misread infix predicate argument commas.
    guard = " and ".join(guards)
    plain = f"{guard} -> {body}" if guard else body
    deontic_body = f"{canonical['modality']}({body})"
    normative = f"{guard} -> {deontic_body}" if guard else deontic_body
    # The statement is a member of each richer grammar's first-order/deontic
    # fragment. This does not assert an absent temporal/cognitive operator.
    formulas = {"fol": plain, "temporal_fol": plain, "deontic_fol": normative,
                "deontic_temporal_fol": normative, "deontic_cec": normative}
    quoted = lambda value: json.dumps(value, ensure_ascii=False)
    slots = [f"source_id->{quoted(source_id)}"]
    for name in ("modality", "actor", "action", "object"):
        slots.append(f"{name}->{quoted(canonical[name])}")
    for name in ("conditions", "exceptions", "temporal"):
        slots.append(f"{name}_count->{len(canonical[name])}")
        slots.extend(f"{name}({index})->{quoted(value)}" for index, value in enumerate(canonical[name]))
    # CanonicalRule sorts temporal atoms independently of parser sidecar order.
    # A typed field must use its atom's index, including when only some atoms
    # have typed records. Sorting the fields also keeps frame bytes stable
    # when an equivalent sidecar list arrives in another order.
    for record in sorted(accepted_records, key=lambda item: item["canonical_temporal_index"]):
        index = record["canonical_temporal_index"]
        slots.extend((f"temporal_kind({index})->{quoted(record['temporal_kind'])}",
                      f"temporal_quantity({index})->{record['quantity']}"))
    formulas["frame_logic"] = f"norm_{_digest(canonical)[:16]}[" + ",".join(slots) + "]."
    records = []
    for target, formula in formulas.items():
        omitted = target in {"fol", "temporal_fol"}
        frame = target == "frame_logic"
        coverage = {
            "scope": "canonical_atom_syntax_projection",
            "modality_encoding": "omitted" if omitted else "frame_value" if frame else "deontic_operator",
            "deontic_operator_count": int(not omitted and not frame),
            "temporal_atom_count": len(canonical["temporal"]),
            "typed_duration_record_count": len(accepted_records),
            "typed_duration_atom_indices": sorted({record["canonical_temporal_index"] for record in accepted_records}),
            "temporal_operator_count": 0,
            "event_calculus_atom_count": 0,
            "cognitive_operator_count": 0,
            "semantic_equivalence_checked": False,
            "admitted": False,
        }
        records.append({
            "target": target, "exported_formula": formula, "source_id": source_id,
            "exporter": __name__ + ".export_canonical_rule_families",
            "export_schema": "canonical-rule-family-syntax/v1", "skipped": False,
            "canonical_rule": canonical, "canonical_rule_sha256": _digest(canonical),
            "atom_bindings": bindings, "temporal_records": accepted_records,
            "projection_omitted_facets": ["modality"] if omitted else [],
            "representation_coverage": coverage,
            "grammar_fragment": "frame_record" if target == "frame_logic" else "source_atom_predicates",
            "temporal_operator_added": False, "event_time_invented": False,
            "semantic_equivalence_checked": False, "admitted": False,
        })
    return records


def _export_rule(rule: Mapping[str, Any], source_text: str, source_id: str,
                 temporal_records: Sequence[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Emit versioned canonical syntax; retain legacy exports as audit evidence."""
    ir = _module("ipfs_datasets_py.logic.deontic.ir")
    exports = _module("ipfs_datasets_py.logic.deontic.prover_syntax")
    element = {
        "source_id": source_id, "text": source_text, "support_text": source_text,
        "source_span": {"start": 0, "end": len(source_text)},
        "support_span": {"start": 0, "end": len(source_text)},
        "actor": rule["actor"], "action": rule["action"], "action_verb": rule["action"],
        "action_object": rule["object"], "modality": rule["modality"],
        "norm_type": {"O": "obligation", "P": "permission", "F": "prohibition"}[rule["modality"]],
        "conditions": list(rule["conditions"]), "exceptions": list(rule["exceptions"]),
        "temporal_constraints": list(rule["temporal"]), "slot_details_scoped": True,
    }
    norm = ir.LegalNormIR.from_parser_element(element)
    legacy = {row["target"]: row for row in exports.build_prover_syntax_records_from_ir(norm)}
    records = export_canonical_rule_families(rule, source_id=source_id, temporal_records=temporal_records)
    for record in records:
        old = legacy.get(record["target"])
        if old is not None:
            record["legacy_export_record"] = old
            family = next(key for key, target in _TARGETS.items() if target == record["target"])
            record["legacy_syntax_diagnostic"] = validate_family_artifact(family, old["exported_formula"])
    return records


def qualify_logic_families(
    source_text: str, compiled_rule: Mapping[str, Any] | None = None, *,
    source_id: str = "span", required_families: Sequence[str] = REQUIRED_FAMILIES,
) -> dict[str, Any]:
    """Bind existing exports and real syntax checks to a caller-compiled rule.

    The caller must have checked the compiler's success status and source/rule
    association. This function does not infer a rule, run a model, call an
    external prover, or silently relax the required family set.
    """
    from .tree_pin import require_workspace_logic_tree
    require_workspace_logic_tree()
    families = list(dict.fromkeys(_ALIASES.get(name, name) for name in required_families))
    source_sha = _text_digest(source_text)
    report: dict[str, Any] = {
        "schema": "autoformal-family-qualification/v1", "source_id": source_id,
        "source_sha256": source_sha, "rule_sha256": None, "passed": False,
        "required_families": families, "families": {}, "goals": [],
        "semantic_equivalence_checked": False, "projection_only": True,
        "admitted": False, "formalized": False, "compiler_source_binding_required": True,
    }
    records: dict[str, dict[str, Any]] = {}
    precondition = ""
    try:
        if not families:
            raise ValueError("empty_required_family_set")
        if not source_text.strip():
            raise ValueError("empty_source_text")
        if not compiled_rule:
            raise ValueError("canonical_compiler_rule_missing")
        contracts = _module("ipfs_datasets_py.logic.legal_ir.canonical_contracts")
        # Autoformal rows include this parser-supplied sidecar for Lake. It is
        # retained and hashed, but is not a field of CanonicalRule/v1.
        canonical_input = dict(compiled_rule)
        temporal_records = canonical_input.pop("temporal_records", None)
        report["input_rule_sha256"] = _digest(compiled_rule)
        if temporal_records is not None:
            report["temporal_records"] = temporal_records
        rule = contracts.CanonicalRule.from_dict(canonical_input).to_dict()
        if "stitch:" in json.dumps(rule):
            raise ValueError("placeholder_rule")
        report["rule_sha256"] = _digest(rule)
        report["canonical_rule"] = rule
        records = {row["target"]: row for row in _export_rule(rule, source_text, source_id, temporal_records or ())}
    except Exception as exc:
        from .tree_pin import LogicTreePinError
        if isinstance(exc, LogicTreePinError):
            raise
        precondition = f"{type(exc).__name__}:{exc}"
    for family in families:
        record = records.get(_TARGETS.get(family, ""))
        if precondition or record is None:
            reason = precondition or ("temporal_fol_exporter_missing" if family == "temporal_fol" else "unsupported_family_or_missing_export")
            row = {"family": family, "passed": False, "syntax_valid": False,
                   "applicability": "unavailable", "formula": "", "diagnostics": [{"code": reason}]}
        else:
            row = validate_family_artifact(family, str(record.get("exported_formula") or ""))
            row["applicability"] = "existing_export_projection"
            row["export_record"] = record
            row["exporter"] = str(record.get("exporter") or "")
            row["source_bound"] = True
            if "representation_coverage" in record:
                row["representation_coverage"] = record["representation_coverage"]
            if record.get("skipped") is True:
                row.update(passed=False, syntax_valid=False)
                row["diagnostics"].append({"code": "exporter_skipped"})
        row.update(source_sha256=source_sha, rule_sha256=report["rule_sha256"],
                   admitted=False, formalized=False, semantic_equivalence_checked=False)
        report["families"][family] = row
        if row["passed"] is not True:
            report["goals"].append({
                "work_kind": "compiler_family_export_repair", "family": family,
                "source_id": source_id, "source_sha256": source_sha,
                "rule_sha256": report["rule_sha256"], "diagnostics": row["diagnostics"],
                "acceptance": "The exact source-bound export must parse without recovery, placeholders, skipped families, or altered acceptance criteria; syntax is not semantic equivalence or Lake admission.",
            })
    report["passed"] = bool(families) and all(row["passed"] is True for row in report["families"].values())
    report["diagnostics"] = [{"code": precondition}] if precondition else []
    return report


# Descriptive compatibility spelling for qualification callers.
validate_logic_families = qualify_logic_families
