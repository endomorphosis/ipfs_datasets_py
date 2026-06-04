"""FOL/TDFOL implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .types import (
    BridgeEvaluationReport,
    GraphProjectionResult,
    LegalIRDocument,
    LogicIRView,
    ProofGateResult,
    RoundTripMetrics,
)

_RESERVED_TDFOL_TERM_PREFIXES = (
    "or",
    "and",
    "not",
    "iff",
    "implies",
    "xor",
)
_RESERVED_TDFOL_TERM_PREFIX = re.compile(
    r"([\(\,]\s*)(" + "|".join(_RESERVED_TDFOL_TERM_PREFIXES) + r")(?=[A-Za-z0-9_])",
    flags=re.IGNORECASE,
)


@dataclass
class FolTdfolBridgeAdapter:
    """Bridge legal norm text into TDFOL formulas and graph records."""

    converter: Optional[Any] = None
    converter_kwargs: Mapping[str, Any] = field(
        default_factory=lambda: {
            "enable_monitoring": False,
            "use_cache": True,
            "use_ml": False,
        }
    )

    name: str = "fol_tdfol"
    target_component: str = "TDFOL.prover"

    def encode(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        """Encode legal text into a TDFOL bridge document."""

        bridge_inputs = _bridge_inputs_from_text(text, converter=self._converter())
        norms = bridge_inputs["norms"]
        resolved_document_id = document_id or _document_id("tdfol", text)
        formula_records = _merge_formula_records(
            _formula_records_from_proof_obligation_rows(
                bridge_inputs["proof_obligation_rows"]
            ),
            _tdfol_formula_records(norms),
        )
        triples = tuple(
            _tdfol_frame_logic_triples(
                resolved_document_id,
                formula_records=formula_records,
            )
        )
        graph_data = _graph_data_from_triples(
            triples,
            graph_id=f"{resolved_document_id}:tdfol-flogic",
                metadata={
                    "source": "tdfol_bridge_ir",
                    "tdfol_formula_count": len(formula_records),
                    "guidance_formula_count": len(
                        bridge_inputs["proof_obligation_rows"]
                    ),
                },
            )
        views = {
            "tdfol_formula": LogicIRView(
                name="tdfol_formula",
                format="tdfol-formula-records",
                source_component="TDFOL.prover",
                payload={
                    "records": [
                        _public_formula_record(record)
                        for record in formula_records
                    ]
                },
                metadata={"formula_count": len(formula_records)},
            ),
            "proof_obligations": LogicIRView(
                name="proof_obligations",
                format="tdfol-proof-obligations",
                source_component="TDFOL.prover",
                payload={
                    "obligations": [
                        {
                            "formula": record["formula"],
                            "source_id": record["source_id"],
                            "target_logic": "TDFOL",
                        }
                        for record in formula_records
                    ]
                },
                metadata={"obligation_count": len(formula_records)},
            ),
            "frame_logic": LogicIRView(
                name="frame_logic",
                format="flogic-triples-v1",
                source_component="TDFOL.prover",
                payload={"triples": [dict(triple) for triple in triples]},
                metadata={"triple_count": len(triples)},
            ),
        }
        if graph_data is not None:
            views["neo4j_graph_data"] = LogicIRView(
                name="neo4j_graph_data",
                format="neo4j-compatible-graph-data",
                source_component="knowledge_graphs.neo4j_compat",
                payload=graph_data.to_dict(),
                metadata={
                    "node_count": graph_data.node_count,
                    "relationship_count": graph_data.relationship_count,
                },
            )

        return (
            LegalIRDocument(
                document_id=resolved_document_id,
                source_text=text,
                normalized_text=" ".join(str(text or "").split()),
                source=source,
                citation=citation or _citation_from_norms(norms),
                views=views,
                frame_logic_triples=triples,
                metadata={
                    "deontic_norm_count": len(norms),
                    "tdfol_formula_count": len(formula_records),
                    "guidance_formula_count": len(
                        bridge_inputs["proof_obligation_rows"]
                    ),
                },
            ),
            {
                "formula_records": formula_records,
                "graph_data": graph_data,
                "norms": norms,
                "proof_obligation_rows": bridge_inputs["proof_obligation_rows"],
            },
        )

    def evaluate(
        self,
        text: str,
        *,
        document_id: Optional[str] = None,
        citation: Optional[str] = None,
        source: str = "us_code",
        source_embedding: Optional[Sequence[float]] = None,
        **_: Any,
    ) -> BridgeEvaluationReport:
        """Run the TDFOL bridge and return optimizer-visible diagnostics."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
        )
        formula_records = list(context["formula_records"])
        proof_gate = _proof_gate_from_tdfol_records(formula_records)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(formula_records))
        failed = max(0, attempted - proof_gate.valid_count)
        parse_failure_ratio = failed / attempted
        no_formula_loss = 0.0 if formula_records else 1.0
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - no_formula_loss),
            cosine_loss=no_formula_loss,
            symbolic_validity_penalty=parse_failure_ratio,
            extra_losses={
                "tdfol_no_formula_loss": no_formula_loss,
                "tdfol_parse_failure_ratio": parse_failure_ratio,
            },
        )
        status = "ok" if formula_records and proof_gate.compiles else "partial"
        if graph_result.graph_failure_penalty:
            status = "partial"
        return BridgeEvaluationReport(
            adapter_name=self.name,
            target_component=self.target_component,
            ir_document=ir_document,
            round_trip=round_trip,
            proof_gate=proof_gate,
            graph_projection=graph_result,
            decoded_text=" ".join(
                str(record.get("formula") or "")
                for record in formula_records
            ),
            status=status,
            metadata={"adapter": "fol_tdfol_bridge_v1"},
        )

    def _converter(self) -> Any:
        if self.converter is not None:
            return self.converter
        from ipfs_datasets_py.logic.deontic import DeonticConverter

        self.converter = DeonticConverter(**dict(self.converter_kwargs))
        return self.converter


def _bridge_inputs_from_text(text: str, *, converter: Any) -> dict[str, list[dict[str, Any]]]:
    result = converter.convert(text)
    metadata = dict(getattr(result, "metadata", {}) or {})
    proof_obligation_rows = _proof_obligation_rows_from_metadata(metadata)
    norms = _deontic_norms_from_metadata(metadata, fallback_text=text)
    if not norms:
        synthesized = _synthesized_norm_from_text(text)
        norms = [synthesized] if synthesized is not None else []
    return {
        "norms": norms,
        "proof_obligation_rows": proof_obligation_rows,
    }


def _deontic_norms_from_metadata(
    metadata: Mapping[str, Any],
    *,
    fallback_text: str,
) -> list[dict[str, Any]]:
    norms = _list_of_dicts(metadata.get("legal_norm_irs"))
    if norms:
        return norms

    legal_norm_ir = metadata.get("legal_norm_ir")
    if isinstance(legal_norm_ir, Mapping):
        norms = [dict(legal_norm_ir)]
    if norms:
        return norms

    parser_elements = _list_of_dicts(metadata.get("parser_elements"))
    if not parser_elements:
        parser_element = metadata.get("parser_element")
        if isinstance(parser_element, Mapping):
            parser_elements = [dict(parser_element)]
    if parser_elements:
        norms = [
            _norm_from_parser_element(
                parser_element,
                index=index,
                fallback_text=fallback_text,
            )
            for index, parser_element in enumerate(parser_elements)
        ]
    if norms:
        return norms

    return []


def _tdfol_formula_records(norms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, norm in enumerate(norms):
        formula = _tdfol_formula_from_norm(norm)
        formula_text = formula.to_string()
        parse_ok = _tdfol_parse_ok(formula_text)
        records.append(
            {
                "formula": formula_text,
                "proof_input": formula_text,
                "formula_object": formula,
                "parse_ok": parse_ok,
                "predicates": sorted(formula.get_predicates()),
                "source_id": str(norm.get("source_id") or f"tdfol:norm:{index}"),
                "source_norm": dict(norm),
            }
        )
    return records


def _formula_records_from_proof_obligation_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        formula_text = str(row.get("formula") or row.get("proof_input") or "").strip()
        if not formula_text:
            continue
        formula_object = coerce_tdfol_formula(
            row.get("formula_object") or row.get("proof_formula_object") or formula_text
        )
        parse_ok = formula_object is not None
        proof_input = (
            formula_object.to_string()
            if formula_object is not None and hasattr(formula_object, "to_string")
            else formula_text
        )
        predicates = sorted(formula_object.get_predicates()) if formula_object is not None else []
        source_id = str(
            row.get("source_id")
            or row.get("proof_obligation_id")
            or f"tdfol:guidance:{index}"
        )
        records.append(
            {
                "formula": proof_input,
                "proof_input": proof_input,
                "formula_object": formula_object,
                "parse_ok": parse_ok,
                "predicates": predicates,
                "source_id": source_id,
                "source_norm": dict(row),
            }
        )
    return records


def _merge_formula_records(
    guidance_records: Sequence[Mapping[str, Any]],
    norm_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for record in tuple(guidance_records) + tuple(norm_records):
        source_id = str(record.get("source_id") or "")
        formula = str(record.get("formula") or "")
        key = (source_id, formula)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(record))
    return merged


def _proof_obligation_rows_from_metadata(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidate_keys = (
        "proof_obligations",
        "proof_obligation_records",
        "deontic_proof_obligations",
        "document_export_tables",
    )
    for key in candidate_keys:
        value = metadata.get(key)
        if key == "document_export_tables" and isinstance(value, Mapping):
            value = value.get("proof_obligations")
        rows.extend(_proof_obligation_rows_from_value(value))
    return rows


def _proof_obligation_rows_from_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        records = value.get("records")
        if isinstance(records, Sequence) and not isinstance(records, (str, bytes)):
            return [dict(item) for item in records if isinstance(item, Mapping)]
        if "formula" in value or "proof_input" in value:
            return [dict(value)]
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _tdfol_formula_from_norm(norm: Mapping[str, Any]) -> Any:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        Constant,
        DeonticFormula,
        DeonticOperator,
        Predicate,
        TemporalFormula,
        TemporalOperator,
    )

    actor = _symbol(norm.get("actor") or "actor")
    action = _predicate_name(norm.get("action") or norm.get("predicate") or "act")
    predicate = Predicate(action, (Constant(actor),))
    modality = str(norm.get("modality") or norm.get("norm_type") or "").lower()
    if "prohib" in modality or "forbid" in modality:
        operator = DeonticOperator.PROHIBITION
    elif "permit" in modality or "may" in modality:
        operator = DeonticOperator.PERMISSION
    else:
        operator = DeonticOperator.OBLIGATION
    inner: Any = predicate
    temporal_text = " ".join(
        str(norm.get(key) or "")
        for key in ("action", "condition", "temporal", "source_text")
    ).lower()
    if any(token in temporal_text for token in ("before", "after", "when", "until")):
        inner = TemporalFormula(TemporalOperator.ALWAYS, predicate)
    return DeonticFormula(operator, inner, agent=Constant(actor))


def coerce_tdfol_formula(formula: Any) -> Optional[Any]:
    """Return a TDFOL formula object from either object or parser-friendly text."""

    return _coerce_tdfol_formula(formula, seen=set())


def _coerce_tdfol_formula(formula: Any, *, seen: set[int]) -> Optional[Any]:
    if formula is None:
        return None
    if hasattr(formula, "to_string") and hasattr(formula, "get_predicates"):
        return formula
    if isinstance(formula, Mapping):
        object_id = id(formula)
        if object_id in seen:
            return None
        seen.add(object_id)
        formula_keys = (
            "formula_object",
            "proof_formula_object",
            "formula",
            "proof_input",
            "proof_formula",
            "tdfol_formula",
            "value",
            "text",
        )
        container_keys = (
            "obligations",
            "proof_obligations",
            "records",
            "formulas",
            "items",
        )
        consumed_keys: set[str] = set()
        for key in formula_keys + container_keys:
            if key not in formula:
                continue
            consumed_keys.add(key)
            value = formula.get(key)
            if value is formula:
                continue
            coerced = _coerce_tdfol_formula(value, seen=seen)
            if coerced is not None:
                return coerced
        for raw_key in sorted(formula.keys(), key=lambda item: str(item)):
            key = str(raw_key)
            if key in consumed_keys:
                continue
            value = formula.get(raw_key)
            if value is formula:
                continue
            coerced = _coerce_tdfol_formula(value, seen=seen)
            if coerced is not None:
                return coerced
        return None
    if isinstance(formula, Sequence) and not isinstance(formula, (str, bytes)):
        object_id = id(formula)
        if object_id in seen:
            return None
        seen.add(object_id)
        for item in formula:
            coerced = _coerce_tdfol_formula(item, seen=seen)
            if coerced is not None:
                return coerced
        return None
    text = str(formula or "").strip()
    if not text:
        return None
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe

        for candidate in _tdfol_parse_candidates(text):
            parsed = parse_tdfol_safe(candidate)
            if parsed is not None:
                return parsed
        return None
    except Exception:
        return None


def _tdfol_parse_candidates(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    candidates: list[str] = []

    def _add(candidate: str) -> None:
        value = str(candidate or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    sanitized = _sanitize_tdfol_formula_text(normalized)
    if sanitized != normalized:
        _add(sanitized)
    _add(_normalize_tdfol_export_formula(normalized))
    _add(normalized)

    if normalized.endswith("."):
        stripped = normalized[:-1].rstrip()
        sanitized_stripped = _sanitize_tdfol_formula_text(stripped)
        if sanitized_stripped != stripped:
            _add(sanitized_stripped)
        _add(_normalize_tdfol_export_formula(stripped))
        _add(stripped)

    return candidates


def _sanitize_tdfol_formula_text(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    # The TDFOL lexer greedily tokenizes short logical keywords ("or", "and",
    # "not", ...) before reading identifiers. Prefix term symbols that begin
    # with those fragments so deterministic bridge formulas remain parseable.
    return _RESERVED_TDFOL_TERM_PREFIX.sub(
        lambda match: f"{match.group(1)}term_{match.group(2).lower()}",
        normalized,
    )


def _normalize_tdfol_export_formula(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    normalized = normalized.strip("`\"'").strip()
    normalized = re.sub(
        r"^\s*(?:formula|proof_formula|proof\s+formula|tdfol_formula|"
        r"tdfol\s+formula|proof_input|proof\s+input|proof_obligation|"
        r"proof\s+obligation|obligation)\s*[:=]\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b([OPF])\s*\[\s*(.*?)\s*\]",
        lambda match: f"{match.group(1)}({match.group(2)})",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized.strip()


def _tdfol_parse_ok(formula: str) -> bool:
    try:
        return coerce_tdfol_formula(formula) is not None
    except Exception:
        return False


def _proof_gate_from_tdfol_records(
    records: Sequence[Mapping[str, Any]],
) -> ProofGateResult:
    attempted = len(records)
    valid = sum(1 for record in records if record.get("parse_ok"))
    failed = attempted - valid
    return ProofGateResult(
        attempted_count=attempted,
        valid_count=valid,
        failed_count=failed,
        verified_by=("tdfol:parser",) if valid else (),
        details=tuple(
            {
                "formula": record.get("formula"),
                "parse_ok": bool(record.get("parse_ok")),
                "source_id": record.get("source_id"),
            }
            for record in records
        ),
    )


def _tdfol_frame_logic_triples(
    document_id: str,
    *,
    formula_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    triples = [
        {"subject": document_id, "predicate": "type", "object": "legal_tdfol_document"}
    ]
    for record in formula_records:
        source_id = str(record.get("source_id") or "")
        if not source_id:
            continue
        triples.extend(
            [
                {"subject": document_id, "predicate": "contains_formula", "object": source_id},
                {"subject": source_id, "predicate": "type", "object": "tdfol_formula"},
                {"subject": source_id, "predicate": "formula", "object": str(record.get("formula") or "")},
                {"subject": source_id, "predicate": "parse_ok", "object": str(bool(record.get("parse_ok"))).lower()},
            ]
        )
        for predicate in record.get("predicates") or []:
            triples.append(
                {"subject": source_id, "predicate": "uses_predicate", "object": str(predicate)}
            )
    return [triple for triple in triples if triple["object"]]


def _graph_data_from_triples(
    triples: Sequence[Mapping[str, str]],
    *,
    graph_id: str,
    metadata: Mapping[str, Any],
) -> Any:
    if not triples:
        return None
    from ipfs_datasets_py.logic.modal.kg_bridge import flogic_triples_to_graph_data

    return flogic_triples_to_graph_data(triples, graph_id=graph_id, metadata=metadata)


def _public_formula_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "formula": record.get("formula"),
        "proof_input": record.get("proof_input"),
        "parse_ok": bool(record.get("parse_ok")),
        "predicates": list(record.get("predicates") or []),
        "source_id": record.get("source_id"),
    }


def _document_id(prefix: str, text: str) -> str:
    digest = hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _citation_from_norms(norms: Sequence[Mapping[str, Any]]) -> Optional[str]:
    if not norms:
        return None
    citation = norms[0].get("canonical_citation")
    return str(citation) if citation else None


def _predicate_name(value: Any) -> str:
    text = str(value or "act").strip().lower()
    chars = [char if char.isalnum() else "_" for char in text]
    name = "_".join(part for part in "".join(chars).split("_") if part)
    if not name:
        return "act"
    if not name[0].isalpha():
        name = f"n_{name}"
    return _tdfol_safe_identifier(name)


def _tdfol_safe_identifier(name: str) -> str:
    candidate = str(name or "").strip().lower()
    if not candidate:
        return "term_symbol"
    if any(candidate.startswith(prefix) for prefix in _RESERVED_TDFOL_TERM_PREFIXES):
        return f"term_{candidate}"
    return candidate


def _symbol(value: Any) -> str:
    symbol = _predicate_name(value)
    if symbol == "act":
        return "actor"
    return symbol


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _norm_from_parser_element(
    parser_element: Mapping[str, Any],
    *,
    index: int,
    fallback_text: str,
) -> dict[str, Any]:
    source_text = str(
        parser_element.get("text")
        or parser_element.get("support_text")
        or fallback_text
        or ""
    ).strip()
    modality = _normalized_modality(
        parser_element.get("modality")
        or parser_element.get("norm_type")
        or parser_element.get("deontic_operator")
        or source_text
    )
    return {
        "action": (
            _first_text_value(parser_element.get("action"))
            or str(parser_element.get("action_verb") or "")
            or _infer_action_from_text(source_text or fallback_text)
        ),
        "actor": (
            _first_text_value(parser_element.get("subject"))
            or str(parser_element.get("actor") or "")
            or _infer_actor_from_text(source_text or fallback_text)
        ),
        "canonical_citation": str(parser_element.get("canonical_citation") or ""),
        "condition": _first_text_value(parser_element.get("conditions")) or "",
        "modality": modality,
        "norm_type": modality,
        "source_id": str(parser_element.get("source_id") or f"tdfol:parser:{index}"),
        "source_text": source_text,
    }


def _synthesized_norm_from_text(text: str) -> Optional[dict[str, Any]]:
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return None
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:12]
    modality = _normalized_modality(normalized_text)
    return {
        "action": _infer_action_from_text(normalized_text),
        "actor": _infer_actor_from_text(normalized_text),
        "canonical_citation": _extract_citation_from_text(normalized_text) or "",
        "condition": "",
        "modality": modality,
        "norm_type": modality,
        "source_id": f"tdfol:text:{digest}",
        "source_text": normalized_text,
    }


def _normalized_modality(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "statement"
    if text in {"o", "obl", "obligation", "obligatory"}:
        return "obligation"
    if text in {"p", "perm", "permission", "permitted"}:
        return "permission"
    if text in {"f", "forbidden", "forbid", "prohibition", "prohibited"}:
        return "prohibition"
    if "shall not" in text or "must not" in text or "may not" in text:
        return "prohibition"
    if any(token in text for token in ("prohibit", "forbid", "forbidden")):
        return "prohibition"
    if re.search(r"\b(shall|must|required|requirement)\b", text):
        return "obligation"
    if re.search(r"\b(may|permitted|permission|authorized)\b", text):
        return "permission"
    if any(token in text for token in ("means", "defined", "definition", "established")):
        return "definition"
    return "statement"


def _first_text_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            candidate = _first_text_value(item)
            if candidate:
                return candidate
    return ""


def _infer_action_from_text(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", str(text or "").lower())
    if not tokens:
        return "act"
    ignored = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "may",
        "must",
        "not",
        "of",
        "on",
        "or",
        "shall",
        "that",
        "the",
        "there",
        "this",
        "to",
        "was",
        "were",
    }
    informative = [token for token in tokens if token not in ignored]
    action_tokens = informative[:6] if informative else tokens[:3]
    return " ".join(action_tokens)


def _infer_actor_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    ignored = {"term", "section", "subsection", "chapter", "title", "part", "clause"}
    for match in re.finditer(r"\bthe\s+([a-z][a-z0-9_]*)\b", lowered):
        candidate = match.group(1).strip()
        if candidate and candidate not in ignored:
            return candidate
    return "actor"


def _extract_citation_from_text(text: str) -> Optional[str]:
    match = re.match(
        r"^\s*([0-9]+\s+u\.?\s*s\.?\s*c\.?\s+[0-9a-z\-\.]+)",
        str(text or ""),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    citation = re.sub(r"\s+", " ", match.group(1)).strip()
    return citation.upper().replace("U. S. C.", "U.S.C.").replace("U S C", "U.S.C.")


__all__ = ["FolTdfolBridgeAdapter", "coerce_tdfol_formula"]
