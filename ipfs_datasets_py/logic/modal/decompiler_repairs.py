"""Source-free deterministic round-trip records for modal Legal IR.

The normal modal decompiler renders an audit-friendly surface and emits many
fine-grained phrase slots.  This module provides the smaller contract used by
hammer repair lanes and learned structural targets.  It deliberately retains
semantic atoms, ordering, and provenance identifiers while never serializing a
source sentence or a character-span payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import (
    ModalIRDocument,
    ModalIRFormula,
)


MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION = "legal-ir-modal-decompiler-repair-v1"
DECOMPILER_CONTRACT_ID = "legal-ir-view/decompiler/v1"

_SOURCE_CONTRACT_BY_FAMILY = {
    "alethic": "legal-ir-view/frame-logic/v1",
    "conditional_normative": "legal-ir-view/deontic/v1",
    "deontic": "legal-ir-view/deontic/v1",
    "dynamic": "legal-ir-view/cec/v1",
    "epistemic": "legal-ir-view/frame-logic/v1",
    "frame": "legal-ir-view/frame-logic/v1",
    "temporal": "legal-ir-view/tdfol/v1",
}
_FORCE_BY_SYMBOL = {
    "F": "prohibition",
    "G": "always",
    "K": "knowledge",
    "O": "obligation",
    "O|": "conditional_obligation",
    "P": "permission",
    "X": "next",
    "[a]": "post_action",
    "◇": "possibility",
    "□": "necessity",
}
_ROLE_ALIASES = {
    "actor": "actor",
    "agent": "actor",
    "subject": "actor",
    "action": "action",
    "verb": "action",
    "object": "object",
    "patient": "object",
    "target": "object",
    "theme": "object",
    "recipient": "recipient",
    "beneficiary": "recipient",
}
_EXCEPTION_CUE_RE = re.compile(
    r"^(except_as_otherwise_provided|except_as_provided_in|except_to_the_extent|"
    r"except_that|except_as|provided_that|provided|unless|except|"
    r"subject_to|notwithstanding)(?:_|$)",
    re.IGNORECASE,
)
_TEMPORAL_CUE_RE = re.compile(
    r"^(not_later_than|no_later_than|within|before|after|until|during|when|"
    r"upon|by|thereafter|only_after)(?:_|$)",
    re.IGNORECASE,
)
_RELATION_BY_TEMPORAL_CUE = {
    "after": "after",
    "before": "before",
    "by": "deadline",
    "during": "during",
    "no_later_than": "deadline",
    "not_later_than": "deadline",
    "only_after": "after",
    "thereafter": "after",
    "until": "until",
    "upon": "after",
    "when": "when",
    "within": "deadline",
}
_OFFSET_RE = re.compile(
    r"(?:within_)?(?P<amount>\d+)_?(?P<unit>business_days?|days?|weeks?|months?|years?)"
    r"(?:_(?P<relation>after|before|from)_?(?P<anchor>.*))?",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}_\d{1,2}_\d{4})\b")
_ATOM_RE = re.compile(r"[a-z0-9]+")
_LOW_INFORMATION = frozenset(
    {"a", "an", "any", "each", "of", "the", "this", "that", "such"}
)


def repair_decompiler_round_trip(
    document_or_sample: Any,
    *,
    source_contract_id: str = "",
    provenance_id: str = "",
) -> dict[str, Any]:
    """Return a canonical structural reconstruction of modal IR.

    ``document_or_sample`` may be a :class:`ModalIRDocument`, an object with a
    ``modal_ir`` attribute, or the equivalent mapping.  Raw source text is used
    only to hash each formula's support and is never returned.
    """

    document = _modal_document(document_or_sample)
    formulas = _formulas(document)
    explicit_contract = _clean_identifier(source_contract_id)
    formula_records = [
        _formula_record(
            formula,
            document=document,
            source_contract_id=explicit_contract or _source_contract_for(formula),
            provenance_id=provenance_id,
        )
        for formula in sorted(formulas, key=_formula_sort_key)
    ]
    source_contracts = sorted(
        {str(item["source_contract_id"]) for item in formula_records if item["source_contract_id"]}
    )
    modality_count = len(
        {
            (item["modality"]["family"], item["operator"])
            for item in formula_records
        }
    )
    role_counts = {
        role: sum(1 for item in formula_records if item["reconstructed_structure"]["roles"].get(role))
        for role in ("actor", "action", "object", "recipient")
    }
    summary = {
        "citation_count": sum(len(item["citation_provenance"]) for item in formula_records),
        "exception_count": sum(len(item["exceptions"]) for item in formula_records),
        "formula_count": len(formula_records),
        "modality_signature_count": modality_count,
        "role_counts": role_counts,
        "temporal_anchor_count": sum(
            len(item["reconstructed_structure"]["temporal_anchors"])
            for item in formula_records
        ),
    }
    identity = {
        "formulas": formula_records,
        "source_contract_ids": source_contracts,
        "structural_summary": summary,
    }
    return {
        "contract_id": DECOMPILER_CONTRACT_ID,
        "document_id": _document_id(document, provenance_id=provenance_id),
        "formulas": formula_records,
        "provenance_ids": _unique(
            [
                _document_id(document, provenance_id=provenance_id),
                *(value for item in formula_records for value in item["provenance_ids"]),
            ]
        ),
        "schema_version": MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION,
        "source_contract_ids": source_contracts,
        "source_copy_policy": "hash_only",
        "structural_signature": _digest(identity),
        "structural_summary": summary,
    }


def decompile_modal_ir_structure(
    document_or_sample: Any,
    *,
    source_contract_id: str = "",
    provenance_id: str = "",
) -> dict[str, Any]:
    """Compatibility name for :func:`repair_decompiler_round_trip`."""

    return repair_decompiler_round_trip(
        document_or_sample,
        source_contract_id=source_contract_id,
        provenance_id=provenance_id,
    )


def validate_decompiler_round_trip_preservation(
    document_or_sample: Any,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the required preservation dimensions without source prose."""

    expected = repair_decompiler_round_trip(document_or_sample)
    observed_formulas = {
        str(item.get("formula_id") or ""): item
        for item in _mapping_sequence(record.get("formulas"))
    }
    dimensions = {
        "citation_provenance": True,
        "exception_scope": True,
        "modality": True,
        "roles": True,
        "structural_summary": record.get("structural_summary") == expected["structural_summary"],
        "temporal_anchors": True,
    }
    missing_formula_ids: list[str] = []
    for expected_formula in expected["formulas"]:
        formula_id = str(expected_formula["formula_id"])
        observed = observed_formulas.get(formula_id)
        if observed is None:
            missing_formula_ids.append(formula_id)
            for dimension in dimensions:
                dimensions[dimension] = False
            continue
        dimensions["modality"] &= all(
            observed.get(key) == expected_formula[key]
            for key in ("operator", "modality")
        )
        observed_structure = _mapping(observed.get("reconstructed_structure"))
        expected_structure = expected_formula["reconstructed_structure"]
        dimensions["roles"] &= observed_structure.get("roles") == expected_structure["roles"]
        dimensions["temporal_anchors"] &= (
            observed_structure.get("temporal_anchors") == expected_structure["temporal_anchors"]
        )
        dimensions["exception_scope"] &= observed.get("exceptions") == expected_formula["exceptions"]
        dimensions["citation_provenance"] &= (
            observed.get("citation_provenance") == expected_formula["citation_provenance"]
            and observed.get("provenance_ids") == expected_formula["provenance_ids"]
        )
    return {
        "dimensions": dimensions,
        "missing_formula_ids": missing_formula_ids,
        "preserved": all(dimensions.values()) and not missing_formula_ids,
        "schema_version": MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION,
        "source_copy_policy": "hash_only",
    }


def _formula_record(
    formula: Any,
    *,
    document: Any,
    source_contract_id: str,
    provenance_id: str,
) -> dict[str, Any]:
    formula_map = _mapping(formula)
    operator = _mapping(_get(formula, "operator", formula_map.get("operator")))
    predicate = _mapping(_get(formula, "predicate", formula_map.get("predicate")))
    provenance = _mapping(_get(formula, "provenance", formula_map.get("provenance")))
    symbol = _clean_identifier(operator.get("symbol"))
    family = _semantic_atom(operator.get("family"), max_tokens=3)
    system = _semantic_atom(operator.get("system"), max_tokens=3)
    label = _semantic_atom(operator.get("label"), max_tokens=5)
    predicate_name = _semantic_atom(predicate.get("name"), max_tokens=10)
    predicate_role = _semantic_atom(predicate.get("role"), max_tokens=4)
    arguments = _argument_records(predicate.get("arguments"), predicate_name=predicate_name)
    roles = _role_bindings(arguments, predicate_name=predicate_name, predicate_role=predicate_role)
    conditions = _clause_records(
        _sequence(_get(formula, "conditions", formula_map.get("conditions"))),
        kind="condition",
    )
    exceptions = _clause_records(
        _sequence(_get(formula, "exceptions", formula_map.get("exceptions"))),
        kind="exception",
    )
    temporal_anchors = _temporal_anchors([*conditions, *exceptions])
    source_id = _clean_identifier(provenance.get("source_id"))
    citation = " ".join(str(provenance.get("citation") or "").split())
    provenance_ids = _unique([provenance_id, source_id])
    citation_provenance = []
    if citation:
        citation_provenance.append(
            {
                "canonical_citation": citation,
                "citation_sha256": hashlib.sha256(citation.encode("utf-8")).hexdigest(),
                "source_id": source_id,
            }
        )
    formula_id = _clean_identifier(
        _get(formula, "formula_id", formula_map.get("formula_id"))
    ) or f"formula:{_digest([family, symbol, predicate_name, arguments])[:20]}"
    source_span_hash = _formula_span_hash(document, provenance)
    structure = {
        "exception_scope": exceptions,
        "modality": {
            "family": family,
            "force": _FORCE_BY_SYMBOL.get(symbol, label or symbol.lower()),
            "label": label,
            "polarity": "negative" if symbol == "F" else "positive",
            "symbol": symbol,
            "system": system,
        },
        "predicate_signature": {
            "arity": len(arguments),
            "name": predicate_name,
            "role": predicate_role,
        },
        "roles": roles,
        "temporal_anchors": temporal_anchors,
    }
    identity = {
        "arguments": arguments,
        "conditions": conditions,
        "exceptions": exceptions,
        "formula_id": formula_id,
        "modality": structure["modality"],
        "predicate": structure["predicate_signature"],
        "provenance_ids": provenance_ids,
        "roles": roles,
        "temporal_anchors": temporal_anchors,
    }
    return {
        "arguments": arguments,
        "citation_provenance": citation_provenance,
        "conditions": conditions,
        "exceptions": exceptions,
        "formula_id": formula_id,
        "modality": structure["modality"],
        "operator": symbol,
        "predicate": structure["predicate_signature"],
        "provenance_ids": provenance_ids,
        "reconstructed_structure": structure,
        "source_contract_id": source_contract_id,
        "source_span_sha256": source_span_hash,
        "structural_signature": _digest(identity),
    }


def _argument_records(value: Any, *, predicate_name: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for position, raw in enumerate(_sequence(value)):
        text = str(raw or "").strip()
        key, separator, body = text.partition(":")
        role = _ROLE_ALIASES.get(_semantic_atom(key, max_tokens=2), "") if separator else ""
        semantic_value = _semantic_atom(body if separator else text, max_tokens=10)
        if not semantic_value:
            continue
        result.append(
            {
                "position": position,
                "role": role or ("actor" if position == 0 else "object"),
                "value": semantic_value,
            }
        )
    if not any(item["role"] == "action" for item in result) and predicate_name:
        result.append(
            {"position": len(result), "role": "action", "value": predicate_name}
        )
    return result


def _role_bindings(
    arguments: Sequence[Mapping[str, Any]],
    *,
    predicate_name: str,
    predicate_role: str,
) -> dict[str, str]:
    roles: dict[str, str] = {"action": predicate_name} if predicate_name else {}
    for item in arguments:
        role = _ROLE_ALIASES.get(str(item.get("role") or ""), "")
        value = _semantic_atom(item.get("value"), max_tokens=10)
        if role and value and role not in roles:
            roles[role] = value
    if predicate_role in _ROLE_ALIASES and predicate_name:
        roles.setdefault(_ROLE_ALIASES[predicate_role], predicate_name)
    return {key: roles[key] for key in ("actor", "action", "object", "recipient") if roles.get(key)}


def _clause_records(values: Sequence[Any], *, kind: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for order, raw in enumerate(values):
        atom = _semantic_atom(raw, max_tokens=12)
        if not atom:
            continue
        cue = _clause_cue(atom, kind=kind)
        scope = atom[len(cue) :].strip("_") if cue and atom.startswith(cue) else atom
        record = {
            "cue": cue or kind,
            "governed_scope": "local_formula",
            "kind": kind,
            "order": order,
            "scope_atom": scope or atom,
        }
        if kind == "exception":
            record["precedence"] = "exception_over_general_rule"
        records.append(record)
    return records


def _clause_cue(atom: str, *, kind: str) -> str:
    matcher = _EXCEPTION_CUE_RE if kind == "exception" else _TEMPORAL_CUE_RE
    match = matcher.match(atom)
    if match:
        return match.group(1).lower()
    if kind == "condition":
        for cue in ("if", "when", "provided_that", "subject_to", "notwithstanding"):
            if atom == cue or atom.startswith(f"{cue}_"):
                return cue
    return ""


def _temporal_anchors(clauses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for clause in clauses:
        cue = str(clause.get("cue") or "")
        scope = str(clause.get("scope_atom") or "")
        temporal_cue = cue if cue in _RELATION_BY_TEMPORAL_CUE else ""
        if not temporal_cue:
            match = re.search(
                r"(?:^|_)(not_later_than|no_later_than|within|before|after|until|"
                r"during|when|upon|by|thereafter|only_after)(?:_|$)",
                scope,
            )
            temporal_cue = match.group(1).lower() if match else ""
        if not temporal_cue:
            continue
        payload = scope
        cue_marker = f"{temporal_cue}_"
        cue_index = payload.find(cue_marker)
        if cue_index >= 0:
            payload = payload[cue_index + len(cue_marker) :]
        record: dict[str, Any] = {
            "clause_kind": str(clause.get("kind") or "condition"),
            "clause_order": int(clause.get("order") or 0),
            "cue": temporal_cue,
            "relation": _RELATION_BY_TEMPORAL_CUE[temporal_cue],
        }
        offset = _OFFSET_RE.search(payload)
        if offset:
            record["offset"] = int(offset.group("amount"))
            record["unit"] = _semantic_atom(offset.group("unit"), max_tokens=2)
            if offset.group("relation"):
                record["relation"] = offset.group("relation").lower()
            anchor = _semantic_atom(offset.group("anchor"), max_tokens=6)
            if anchor:
                record["anchor"] = anchor
        date_match = _DATE_RE.search(payload)
        if date_match:
            record["date_anchor"] = date_match.group(0).replace("_", "-")
        if "anchor" not in record and "date_anchor" not in record and payload:
            record["anchor"] = _semantic_atom(payload, max_tokens=6)
        anchors.append(record)
    return anchors


def _formula_span_hash(document: Any, provenance: Mapping[str, Any]) -> str:
    source = _document_source(document)
    try:
        start = max(0, int(provenance.get("start_char") or 0))
        end = max(start, int(provenance.get("end_char") or 0))
    except (TypeError, ValueError):
        start, end = 0, 0
    if source and end > start:
        value = source[start : min(end, len(source))]
    else:
        value = ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def _source_contract_for(formula: Any) -> str:
    operator = _mapping(_get(formula, "operator"))
    family = _semantic_atom(operator.get("family"), max_tokens=3)
    return _SOURCE_CONTRACT_BY_FAMILY.get(family, "legal-ir-view/frame-logic/v1")


def _modal_document(value: Any) -> Any:
    nested = _get(value, "modal_ir")
    return nested if nested is not None else value


def _formulas(document: Any) -> list[Any]:
    return list(_sequence(_get(document, "formulas")))


def _document_source(document: Any) -> str:
    return str(_get(document, "normalized_text") or "")


def _document_id(document: Any, *, provenance_id: str = "") -> str:
    return _clean_identifier(
        provenance_id or _get(document, "document_id") or _get(document, "sample_id")
    )


def _formula_sort_key(formula: Any) -> str:
    return _clean_identifier(_get(formula, "formula_id"))


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        return dict(converted) if isinstance(converted, Mapping) else {}
    if value is None:
        return {}
    return {
        key: getattr(value, key)
        for key in (
            "arguments",
            "citation",
            "conditions",
            "end_char",
            "exceptions",
            "family",
            "formula_id",
            "label",
            "metadata",
            "name",
            "operator",
            "predicate",
            "provenance",
            "role",
            "source_id",
            "start_char",
            "symbol",
            "system",
        )
        if hasattr(value, key)
    }


def _mapping_sequence(value: Any) -> list[dict[str, Any]]:
    return [_mapping(item) for item in _sequence(value) if _mapping(item)]


def _sequence(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return list(value)
    return [value]


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _semantic_atom(value: Any, *, max_tokens: int) -> str:
    tokens = _ATOM_RE.findall(str(value or "").lower())
    while tokens and tokens[0] in _LOW_INFORMATION:
        tokens.pop(0)
    return "_".join(tokens[:max(1, int(max_tokens))])


def _clean_identifier(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "DECOMPILER_CONTRACT_ID",
    "MODAL_DECOMPILER_REPAIR_SCHEMA_VERSION",
    "decompile_modal_ir_structure",
    "repair_decompiler_round_trip",
    "validate_decompiler_round_trip_preservation",
]
