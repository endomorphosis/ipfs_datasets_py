"""FOL/TDFOL implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
import json
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
_DEONTIC_EXPORT_OPERATOR_ALIASES = {
    "obligation": "O",
    "obligatory": "O",
    "required": "O",
    "permission": "P",
    "permitted": "P",
    "prohibition": "F",
    "forbidden": "F",
    "impermissible": "F",
}
_DEONTIC_EXPORT_OPERATOR_PATTERN = re.compile(
    r"\b("
    + "|".join(
        re.escape(name)
        for name in sorted(_DEONTIC_EXPORT_OPERATOR_ALIASES, key=len, reverse=True)
    )
    + r")\s*\(",
    flags=re.IGNORECASE,
)
_TDFOL_FORMULA_EXPORT_KEYS = (
    "formula_object",
    "proof_formula_object",
    "formula",
    "candidate_formula",
    "formula_candidate",
    "compiler_formula",
    "program_formula",
    "proof_input",
    "proof_formula",
    "proof_candidate",
    "tdfol_formula",
    "tdfol",
    "proof_obligation",
    "obligation",
    "obligation_formula",
    "exported_formula",
    "target_formula",
    "proof_goal",
    "goal",
    "theorem",
    "theorem_formula",
    "claim",
    "claims",
    "assertion",
    "assertions",
    "proposition",
    "propositions",
    "logical_form",
    "logic_formula",
    "normalized_formula",
    "normalized_proof",
    "expression",
    "value",
    "text",
)
_TDFOL_CONTAINER_EXPORT_KEYS = (
    "obligations",
    "proof_obligations",
    "records",
    "rows",
    "items",
    "formulas",
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
        compiler_guidance: Optional[Mapping[str, Any]] = None,
    ) -> tuple[LegalIRDocument, Mapping[str, Any]]:
        """Encode legal text into a TDFOL bridge document."""

        bridge_inputs = _bridge_inputs_from_text(text, converter=self._converter())
        norms = bridge_inputs["norms"]
        resolved_document_id = document_id or _document_id("tdfol", text)
        compiler_guidance_records = _formula_records_from_compiler_guidance(
            text,
            compiler_guidance,
            norms=norms,
        )
        formula_records = _merge_formula_records(
            compiler_guidance_records,
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
                "compiler_guidance_formula_count": len(
                    compiler_guidance_records
                ),
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
                    "compiler_guidance_formula_count": len(
                        compiler_guidance_records
                    ),
                    "guidance_formula_count": len(
                        bridge_inputs["proof_obligation_rows"]
                    ),
                    "compiler_guidance_applied": bool(
                        compiler_guidance_records
                    ),
                },
            ),
            {
                "formula_records": formula_records,
                "graph_data": graph_data,
                "norms": norms,
                "compiler_guidance_records": compiler_guidance_records,
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
        compiler_guidance: Optional[Mapping[str, Any]] = None,
        **_: Any,
    ) -> BridgeEvaluationReport:
        """Run the TDFOL bridge and return optimizer-visible diagnostics."""

        ir_document, context = self.encode(
            text,
            document_id=document_id,
            citation=citation,
            source=source,
            source_embedding=source_embedding,
            compiler_guidance=compiler_guidance,
        )
        formula_records = list(context["formula_records"])
        proof_gate = _proof_gate_from_tdfol_records(formula_records)
        graph_result = GraphProjectionResult.from_graph_data(context["graph_data"])
        attempted = max(1, len(formula_records))
        failed = max(0, attempted - proof_gate.valid_count)
        parse_failure_ratio = failed / attempted
        compiler_ir_cross_entropy_loss = parse_failure_ratio
        compiler_ir_cosine_similarity = max(
            0.0,
            1.0 - compiler_ir_cross_entropy_loss,
        )
        no_formula_loss = 0.0 if formula_records else 1.0
        legal_ir_view_cross_entropy_loss = max(
            0.0,
            parse_failure_ratio + no_formula_loss,
        )
        round_trip = RoundTripMetrics(
            cosine_similarity=max(0.0, 1.0 - no_formula_loss),
            cosine_loss=no_formula_loss,
            cross_entropy_loss=legal_ir_view_cross_entropy_loss,
            symbolic_validity_penalty=parse_failure_ratio,
            extra_losses={
                "compiler_ir_cross_entropy_loss": compiler_ir_cross_entropy_loss,
                "compiler_ir_cosine_similarity": compiler_ir_cosine_similarity,
                "tdfol_no_formula_loss": no_formula_loss,
                "tdfol_parse_failure_ratio": parse_failure_ratio,
                "legal_ir_view_cross_entropy_loss": legal_ir_view_cross_entropy_loss,
                "source_copy_reward_hack_penalty": 0.0,
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
            metadata={
                "adapter": "fol_tdfol_bridge_v1",
                "compiler_guidance_applied": bool(
                    context["compiler_guidance_records"]
                ),
                "compiler_guidance_routes": sorted(
                    {
                        str(record.get("compiler_guidance_route") or "")
                        for record in context["compiler_guidance_records"]
                        if record.get("compiler_guidance_route")
                    }
                ),
                "compiler_ir_cross_entropy_loss": compiler_ir_cross_entropy_loss,
                "compiler_ir_cosine_similarity": compiler_ir_cosine_similarity,
            },
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
        formula_text = str(_formula_text_from_proof_obligation_row(row)).strip()
        if not formula_text:
            continue
        formula_source = (
            row.get("formula_object") or row.get("proof_formula_object") or formula_text
        )
        formula_object = coerce_tdfol_formula(formula_source)
        if formula_object is None:
            formula_object = _tdfol_formula_from_raw_proof_obligation_row(
                row,
                fallback_text=formula_text,
                index=index,
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


def _tdfol_formula_from_raw_proof_obligation_row(
    row: Mapping[str, Any],
    *,
    fallback_text: str,
    index: int,
) -> Optional[Any]:
    """Synthesize a parseable TDFOL formula for legal-text obligation rows."""

    text = _raw_legal_text_from_proof_obligation_row(row) or fallback_text
    if not _looks_like_legal_text_export(text):
        return None
    norm = _synthesized_norm_from_text(text)
    if norm is None:
        return None
    norm["source_id"] = str(
        row.get("source_id")
        or row.get("proof_obligation_id")
        or f"tdfol:guidance:raw:{index}"
    )
    return _tdfol_formula_from_norm(norm)


def _raw_legal_text_from_proof_obligation_row(row: Mapping[str, Any]) -> str:
    for key in (
        "text",
        "support_text",
        "source_text",
        "obligation_text",
        "proof_obligation_text",
        "obligation",
        "value",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _looks_like_legal_text_obligation(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).lower()
    if not normalized:
        return False
    if _looks_like_tdfol_formula(normalized):
        return False
    return bool(
        re.search(
            r"\b(shall|must|may|authorized|required|prohibited|forbidden|"
            r"repealed|omitted|established|means|defined)\b",
            normalized,
        )
    )


def _looks_like_legal_text_export(text: str) -> bool:
    """Return True for raw statutory prose exported in place of a formula."""

    normalized = " ".join(str(text or "").split()).lower()
    if not normalized:
        return False
    if _looks_like_tdfol_formula(normalized):
        return False
    return _looks_like_legal_text_obligation(normalized) or bool(
        re.search(
            r"\b(?:u\.?\s*s\.?\s*c\.?|united states code|section|sections?|"
            r"chapter|subchapter|part|pub\.?\s*l\.?|stat\.|act)\b",
            normalized,
        )
    )


def _formula_text_from_proof_obligation_row(row: Mapping[str, Any]) -> str:
    for key in _TDFOL_FORMULA_EXPORT_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
        extracted = _tdfol_formula_text_from_json_value(value)
        if extracted:
            return extracted
    return _tdfol_formula_text_from_json_value(row)


def _merge_formula_records(
    *record_groups: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for records in record_groups:
        for record in records:
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
        rows: list[dict[str, Any]] = []
        for key in (
            "records",
            "rows",
            "obligations",
            "proof_obligations",
            "items",
            "formulas",
        ):
            records = value.get(key)
            if isinstance(records, Sequence) and not isinstance(records, (str, bytes)):
                rows.extend(dict(item) for item in records if isinstance(item, Mapping))
        if rows:
            return rows
        if any(
            key in value
            for key in _TDFOL_FORMULA_EXPORT_KEYS
        ):
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
    operator_context = " ".join(
        str(norm.get(key) or "") for key in ("modality", "norm_type", "action")
    ).lower()
    permission_context = " ".join(
        str(norm.get(key) or "")
        for key in ("modality", "norm_type", "source_text")
    ).lower()
    prohibition_context = " ".join(
        str(norm.get(key) or "")
        for key in ("modality", "norm_type", "action", "source_text")
    ).lower()
    if (
        "prohib" in prohibition_context
        or "forbid" in prohibition_context
        or re.search(r"\b(?:shall|must|may)\s+not\b", prohibition_context)
    ):
        operator = DeonticOperator.PROHIBITION
    elif (
        re.search(r"\b(?:permission|permitted)\b", permission_context)
        or re.search(r"\bmay\b", permission_context)
        or re.search(r"\bauthori[sz]ed\b", permission_context)
    ):
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


def _formula_records_from_compiler_guidance(
    text: str,
    compiler_guidance: Optional[Mapping[str, Any]],
    *,
    norms: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    guidance = _tdfol_compiler_guidance_signal(compiler_guidance)
    if not guidance["active"]:
        return []
    formula = _tdfol_guidance_formula(
        text,
        norms=norms,
        guidance=guidance,
    )
    formula_text = formula.to_string()
    parse_ok = _tdfol_parse_ok(formula_text)
    source_id = f"tdfol:compiler_guidance:{guidance['route']}"
    return [
        {
            "formula": formula_text,
            "proof_input": formula_text,
            "formula_object": formula,
            "parse_ok": parse_ok,
            "predicates": sorted(formula.get_predicates()),
            "source_id": source_id,
            "source_norm": {
                "compiler_guidance_route": guidance["route"],
                "compiler_guidance_semantic_overlay_terms": tuple(
                    guidance["semantic_terms"]
                ),
                "compiler_guidance_surface_features": tuple(
                    guidance["surface_features"]
                ),
            },
            "compiler_guidance_route": guidance["route"],
            "compiler_guidance_semantic_overlay_terms": tuple(
                guidance["semantic_terms"]
            ),
            "compiler_guidance_surface_features": tuple(
                guidance["surface_features"]
            ),
        }
    ]


def _tdfol_compiler_guidance_signal(
    compiler_guidance: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(compiler_guidance, Mapping):
        return {
            "active": False,
            "route": "",
            "semantic_terms": (),
            "surface_features": (),
        }

    routes = _tdfol_guidance_routes(compiler_guidance)
    target_components = _tdfol_guidance_target_components(compiler_guidance)

    semantic_terms = _guidance_tokens(
        compiler_guidance.get("compiler_guidance_semantic_overlay_terms")
    )
    surface_features = _guidance_tokens(
        compiler_guidance.get("compiler_guidance_surface_features")
    )
    route = "repair_tdfol_bridge_parse"
    has_route = route in routes or _has_tdfol_parse_repair_evidence(
        compiler_guidance
    )
    conditioned_temporal = any(
        term in {"if", "when"} for term in semantic_terms
    ) or any("conditioned+temporal" in feature for feature in surface_features)
    has_deontic_surface = (
        "shall" in semantic_terms
        or "may" in semantic_terms
        or any("polarity-template:" in feature for feature in surface_features)
    )
    targeted_tdfol = (
        not target_components
        or "tdfol.prover" in target_components
        or "tdfol" in target_components
    )
    return {
        "active": bool(
            has_route
            and targeted_tdfol
            and (
                (conditioned_temporal and has_deontic_surface)
                or _has_packet_tdfol_guidance_evidence(compiler_guidance)
            )
        ),
        "route": route if has_route else "",
        "semantic_terms": tuple(sorted(semantic_terms)),
        "surface_features": tuple(sorted(surface_features)),
    }


def _tdfol_guidance_routes(compiler_guidance: Mapping[str, Any]) -> set[str]:
    """Extract route hints from daemon and packet-shaped compiler guidance."""

    routes: set[str] = set()

    def add_route(value: Any) -> None:
        route = _normalized_guidance_token(value)
        if route:
            routes.add(route)

    route_keys = (
        "route",
        "action",
        "original_action",
        "compiler_guidance_route",
    )

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for route in value.keys():
                add_route(route)
            for nested_key in route_keys:
                add_route(value.get(nested_key))
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                if isinstance(item, Mapping):
                    for nested_key in route_keys:
                        add_route(item.get(nested_key))
                else:
                    add_route(item)
            return
        add_route(value)

    for key in (
        "compiler_guidance_todo_routes",
        "top_todo_routes",
        "todo_routes",
    ):
        value = compiler_guidance.get(key)
        if value is not None:
            collect(value)

    for key in route_keys:
        add_route(compiler_guidance.get(key))

    for bundle in _tdfol_guidance_bundles(compiler_guidance):
        collect(bundle)
        for nested_routes_key in (
            "compiler_guidance_todo_routes",
            "top_todo_routes",
            "todo_routes",
        ):
            if nested_routes_key in bundle:
                collect(bundle.get(nested_routes_key))

    attribution = compiler_guidance.get("compiler_guidance_attribution")
    if isinstance(attribution, Mapping):
        collect(attribution.get("todo_routes"))

    for evidence in _tdfol_guidance_evidence_records(compiler_guidance):
        collect(evidence)

    return routes


def _tdfol_guidance_target_components(
    compiler_guidance: Mapping[str, Any],
) -> set[str]:
    components: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key in (
                "target_component",
                "target_view",
                "predicted_view",
                "target",
            ):
                collect(value.get(key))
            collect(value.get("legal_ir_underrepresented_components"))
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                collect(item)
            return
        component = _normalized_guidance_token(value)
        if component:
            components.add(component)

    collect(compiler_guidance)
    for bundle in _tdfol_guidance_bundles(compiler_guidance):
        collect(bundle)
    for evidence in _tdfol_guidance_evidence_records(compiler_guidance):
        collect(evidence)
    return components


def _has_packet_tdfol_guidance_evidence(
    compiler_guidance: Mapping[str, Any],
) -> bool:
    if _tdfol_guidance_target_components(compiler_guidance) & {
        "tdfol.prover",
        "tdfol",
    }:
        return True
    if compiler_guidance.get("compiler_guidance_quality_gate") == "pass":
        return True
    if _has_tdfol_parse_repair_evidence(compiler_guidance):
        return True
    return any(
        str(bundle.get("program_synthesis_scope") or "").strip().lower()
        == "tdfol"
        for bundle in _tdfol_guidance_bundles(compiler_guidance)
    )


def _has_tdfol_parse_repair_evidence(
    compiler_guidance: Mapping[str, Any],
) -> bool:
    """Detect packet evidence that names the TDFOL parse-repair failure."""

    for evidence in _tdfol_guidance_evidence_records(compiler_guidance):
        target_metrics = _guidance_tokens(evidence.get("target_metrics"))
        failure_name = _normalized_guidance_token(
            evidence.get("bridge_failure_name") or evidence.get("failure_name")
        )
        target_lane = _normalized_guidance_token(
            evidence.get("target_file_lane")
            or evidence.get("program_synthesis_scope")
            or evidence.get("scope")
        )
        target_view = _normalized_guidance_token(
            evidence.get("target_view")
            or evidence.get("predicted_view")
            or evidence.get("target_component")
            or evidence.get("target")
        )
        if (
            (
                failure_name == "tdfol_parse_failure_ratio"
                or "tdfol_parse_failure_ratio" in target_metrics
            )
            and (
                target_lane == "tdfol"
                or target_view in {"tdfol.prover", "tdfol"}
            )
        ):
            return True
    return False


def _tdfol_guidance_evidence_records(
    compiler_guidance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            records.append(dict(value))
            return
        if isinstance(value, str):
            parsed = _tdfol_guidance_json_value(value)
            if parsed is not None and parsed is not value:
                collect(parsed)
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                collect(item)

    for key in (
        "evidence",
        "compiler_guidance_evidence",
        "hint_evidence",
        "metric_evidence",
    ):
        collect(compiler_guidance.get(key))
    return records


def _tdfol_guidance_bundles(
    compiler_guidance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for key in (
        "bundle",
        "semantic_bundle_key",
        "compiler_guidance_bundle",
        "vector_bundle",
    ):
        bundle = _tdfol_guidance_mapping(compiler_guidance.get(key))
        if bundle:
            bundles.append(bundle)
    return bundles


def _tdfol_guidance_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text[0] not in "{[":
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if isinstance(parsed, Mapping):
        return dict(parsed)
    return {}


def _tdfol_guidance_json_value(value: str) -> Any:
    """Parse JSON-shaped guidance strings without treating plain text as data."""

    text = str(value or "").strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _tdfol_guidance_formula(
    text: str,
    *,
    norms: Sequence[Mapping[str, Any]],
    guidance: Mapping[str, Any],
) -> Any:
    from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
        BinaryFormula,
        Constant,
        DeonticFormula,
        DeonticOperator,
        LogicOperator,
        Predicate,
        TemporalFormula,
        TemporalOperator,
        UnaryFormula,
    )

    source_norm = norms[0] if norms else _synthesized_norm_from_text(text) or {}
    actor = _symbol(source_norm.get("actor") or _infer_actor_from_text(text))
    action_hint = (
        source_norm.get("action")
        if not str(source_norm.get("source_id") or "").startswith("tdfol:text:")
        else ""
    )
    action = _predicate_name(
        action_hint
        or source_norm.get("predicate")
        or _infer_guidance_action_from_text(text)
    )
    condition_name = _predicate_name(
        source_norm.get("condition") or _infer_condition_from_text(text)
    )
    consequence: Any = Predicate(action, (Constant(actor),))
    semantic_terms = set(guidance.get("semantic_terms") or ())
    surface_features = set(guidance.get("surface_features") or ())
    negative_scope = "not" in semantic_terms or any(
        "negative_scope" in feature for feature in surface_features
    )
    if negative_scope:
        consequence = UnaryFormula(LogicOperator.NOT, consequence)

    modality_text = " ".join(
        (
            str(source_norm.get("modality") or source_norm.get("norm_type") or ""),
            " ".join(sorted(semantic_terms)),
            " ".join(sorted(surface_features)),
        )
    ).lower()
    if "permission" in modality_text or "may" in semantic_terms:
        deontic_operator = DeonticOperator.PERMISSION
    elif "obligation" in modality_text or "shall" in semantic_terms:
        deontic_operator = DeonticOperator.OBLIGATION
    elif "prohibition" in modality_text or "prohibit" in modality_text:
        deontic_operator = DeonticOperator.PROHIBITION
    else:
        deontic_operator = DeonticOperator.OBLIGATION

    implication = BinaryFormula(
        LogicOperator.IMPLIES,
        Predicate(condition_name, (Constant("context"),)),
        DeonticFormula(deontic_operator, consequence, agent=Constant(actor)),
    )
    return TemporalFormula(TemporalOperator.ALWAYS, implication)


def _guidance_tokens(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {
            token
            for token in (_normalized_guidance_token(item) for item in value.keys())
            if token
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {
            token
            for token in (_normalized_guidance_token(item) for item in value)
            if token
        }
    if isinstance(value, str):
        return {
            token
            for token in (
                _normalized_guidance_token(item)
                for item in re.split(r"[\s,;|]+", value)
            )
            if token
        }
    token = _normalized_guidance_token(value)
    return {token} if token else set()


def _normalized_guidance_token(value: Any) -> str:
    return str(value or "").strip().lower()


def _infer_condition_from_text(text: str) -> str:
    normalized = " ".join(str(text or "").split())
    lowered = normalized.lower()
    match = re.search(
        r"\b(?:if|when)\s+(.+?)(?:,\s*|\s+shall\b|\s+must\b|\s+may\b)",
        lowered,
    )
    if match:
        return match.group(1)
    if " when " in f" {lowered} ":
        return "when_condition"
    if " if " in f" {lowered} ":
        return "if_condition"
    return "guidance_condition"


def _infer_guidance_action_from_text(text: str) -> str:
    lowered = " ".join(str(text or "").lower().split())
    match = re.search(
        r"\b(?:shall|must|may)\s+(?:not\s+)?(.+?)(?:\.|;|$)",
        lowered,
    )
    if match:
        return match.group(1)
    return _infer_action_from_text(text)


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
            *_TDFOL_FORMULA_EXPORT_KEYS,
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
    export_normalized = _normalize_tdfol_export_formula(normalized)
    _add(export_normalized)
    export_sanitized = _sanitize_tdfol_formula_text(export_normalized)
    if export_sanitized != export_normalized:
        _add(export_sanitized)
    _add(normalized)

    if normalized.endswith("."):
        stripped = normalized[:-1].rstrip()
        sanitized_stripped = _sanitize_tdfol_formula_text(stripped)
        if sanitized_stripped != stripped:
            _add(sanitized_stripped)
        stripped_export = _normalize_tdfol_export_formula(stripped)
        _add(stripped_export)
        stripped_export_sanitized = _sanitize_tdfol_formula_text(stripped_export)
        if stripped_export_sanitized != stripped_export:
            _add(stripped_export_sanitized)
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
    normalized = _strip_tdfol_line_comment(normalized)
    normalized = _unwrap_tdfol_fenced_export(normalized)
    normalized = _unwrap_tdfol_json_export(normalized)
    normalized = _unwrap_tdfol_targeted_export(normalized)
    normalized = _normalize_deontic_text_label_export(normalized)
    normalized = _unwrap_tdfol_assignment_export(normalized)
    normalized = _unwrap_tdfol_key_value_export(normalized)
    normalized = _normalize_deontic_operator_aliases(normalized)
    normalized = _normalize_deontic_label_export(normalized)
    normalized = _normalize_deontic_agent_annotation_export(normalized)
    normalized, proof_label_count = re.subn(
        r"^\s*(?:formula|proof_formula|proof\s+formula|tdfol_formula|"
        r"tdfol\s+formula|proof_input|proof\s+input|proof_obligation|"
        r"proof\s+obligation|obligation)\s*[:=]\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    raw_obligation_formula = (
        _formula_from_labeled_raw_proof_obligation(normalized)
        if proof_label_count
        else ""
    )
    if raw_obligation_formula:
        normalized = raw_obligation_formula
    normalized = re.sub(
        r"^\s*(?:TDFOL(?:[\s.]prover)?|target_component\s*[:=]\s*TDFOL(?:[\s.]prover)?)\s*[:=]\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"^\s*TDFOL(?:[\s.]prover)?\s+"
        r"(?:proof_obligation|proof\s+obligation|obligation|goal|claim)"
        r"\s*[:=]\s*",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = normalized.strip("`\"'").strip()
    normalized = _unwrap_tdfol_multiline_export(normalized)
    normalized = _unwrap_tdfol_export_wrapper(normalized)
    normalized = re.sub(
        r"\b([OPF])\s*\[\s*(.*?)\s*\]",
        lambda match: f"{match.group(1)}({match.group(2)})",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\b([OPF])\s*\{\s*(.*?)\s*\}",
        lambda match: f"{match.group(1)}({match.group(2)})",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = _normalize_deontic_argument_export(normalized)
    normalized = _normalize_raw_deontic_text_export(normalized)
    normalized = re.sub(r",\s*(?=\))", "", normalized)
    normalized = re.sub(r"(:[0-9A-Za-z_-]+)\.(?=\s*[\),])", r"\1", normalized)
    return normalized.strip()


def _unwrap_tdfol_targeted_export(text: str) -> str:
    """Drop TDFOL.prover target wrappers around proof-obligation formulas."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    patterns = (
        r"(?is)^\s*TDFOL(?:[\s.]prover)?\s*(?:=>|->|:)\s*(.+)$",
        r"(?is)^\s*TDFOL(?:[\s.]prover)?\s+"
        r"(?:proof_obligations?|proof\s+obligations?|tdfol_formulas?|"
        r"tdfol\s+formulas?|obligations?|goals?|claims?)(?:\s+view)?\s*[:=]\s*(.+)$",
        r"(?is)^\s*(?:target_logic|target_component|target_view|"
        r"predicted_view)\s*[:=]\s*TDFOL(?:[\s.]prover)?\s*(?:[,;]|=>|->)\s*(.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            candidate = match.group(1).strip("`\"'").strip()
            formula = _extract_balanced_tdfol_formula(candidate)
            if formula:
                return formula
            extracted = _tdfol_formula_text_from_export_payload(candidate)
            return extracted or candidate
    return normalized


def _unwrap_tdfol_assignment_export(text: str) -> str:
    """Extract formula text from compact key/value proof exports."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    for key in _TDFOL_FORMULA_EXPORT_KEYS:
        value = _extract_tdfol_key_value(normalized, key)
        if value:
            normalized_value = _normalize_tdfol_export_value(value)
            raw_obligation_formula = _formula_from_labeled_raw_proof_obligation(
                normalized_value
            )
            return raw_obligation_formula or normalized_value
    for key in _TDFOL_CONTAINER_EXPORT_KEYS:
        value = _extract_tdfol_key_value(normalized, key)
        if value:
            extracted = _tdfol_formula_text_from_export_payload(
                value.strip("`\"'").strip()
            )
            if extracted:
                return extracted
    return normalized


def _unwrap_tdfol_fenced_export(text: str) -> str:
    """Extract formula text from Markdown-style proof export fences."""

    normalized = str(text or "").strip()
    if not normalized.startswith("```"):
        return normalized
    match = re.match(
        r"(?is)^```[ \t]*(?:tdfol|logic|formula|proof)?[ \t]*\n?(.*?)\n?```$",
        normalized,
    )
    if not match:
        return normalized
    return match.group(1).strip()


def _unwrap_tdfol_multiline_export(text: str) -> str:
    """Drop labels/provenance lines around a single exported TDFOL formula."""

    normalized = str(text or "").strip()
    if "\n" not in normalized:
        return normalized
    for line in normalized.splitlines():
        candidate = _tdfol_export_line_candidate(line)
        if not candidate:
            continue
        formula = _extract_balanced_tdfol_formula(candidate)
        if formula:
            return formula
    return normalized


def _tdfol_export_line_candidate(line: str) -> str:
    candidate = str(line or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", candidate).strip()
    candidate = re.sub(
        r"^\s*(?:formula|proof_formula|proof\s+formula|tdfol_formula|"
        r"tdfol\s+formula|proof_input|proof\s+input|proof_obligations?|"
        r"proof\s+obligations?|obligations?)\s*[:=]\s*",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()
    return candidate


def _extract_balanced_tdfol_formula(text: str) -> str:
    candidate = str(text or "").strip().strip("`\"'").strip()
    start = _tdfol_formula_start_index(candidate)
    if start < 0:
        return ""
    if start > 0 and re.search(r"[A-Za-z_]", candidate[:start]):
        return ""
    candidate = candidate[start:].strip()
    if not _looks_like_tdfol_formula(candidate):
        return ""
    if candidate.startswith(("forall", "exists", "∀", "∃")):
        return candidate.rstrip(".").strip()
    open_index = candidate.find("(")
    if open_index < 0:
        return candidate.rstrip(".").strip()
    close_index = _matching_paren_index(candidate, open_index)
    if close_index is None:
        return ""
    return candidate[: close_index + 1].strip()


def _tdfol_formula_start_index(text: str) -> int:
    match = re.search(r"(?is)(?:forall|exists|∀|∃)\b", text)
    if match:
        return match.start()
    match = re.search(
        r"(?is)(?:forall|exists|[OPFGX]|□|◊|¬|[A-Za-z_][A-Za-z0-9_-]*)\s*\(",
        text,
    )
    return match.start() if match else -1


def _normalize_deontic_operator_aliases(text: str) -> str:
    """Convert named deontic exports (Obligation/Permitted/etc.) to O/P/F."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    return _DEONTIC_EXPORT_OPERATOR_PATTERN.sub(
        lambda match: (
            f"{_DEONTIC_EXPORT_OPERATOR_ALIASES[match.group(1).lower()]}("
        ),
        normalized,
    )


def _normalize_deontic_label_export(text: str) -> str:
    """Convert label-style deontic exports such as O: action(...) to O(action(...))."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    match = re.match(
        r"(?is)^([OPF])\s*:\s*(.+)$",
        normalized,
    )
    if not match:
        return normalized
    formula = _extract_balanced_tdfol_formula(match.group(2).strip())
    if not formula:
        formula = match.group(2).strip().rstrip(".").strip()
    if not formula:
        return normalized
    return f"{match.group(1).upper()}({formula})"


def _normalize_deontic_text_label_export(text: str) -> str:
    """Convert named raw-text deontic labels into parser-ready formulas."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    operator_names = "|".join(
        re.escape(name)
        for name in sorted(_DEONTIC_EXPORT_OPERATOR_ALIASES, key=len, reverse=True)
    )
    match = re.match(rf"(?is)^({operator_names})\s*[:=]\s*(.+)$", normalized)
    if not match:
        return normalized
    operator = _DEONTIC_EXPORT_OPERATOR_ALIASES[match.group(1).lower()]
    payload = match.group(2).strip().strip("`\"'").strip()
    if not payload:
        return normalized
    formula = _extract_balanced_tdfol_formula(payload)
    if formula:
        return f"{operator}({formula})"
    raw_formula = _formula_from_raw_deontic_text_argument(operator, payload)
    return raw_formula or normalized


def _normalize_deontic_agent_annotation_export(text: str) -> str:
    """Drop parser-incompatible deontic agent annotations around formulas.

    CEC/DCEC and TDFOL pretty printers commonly emit O[agent](phi) or
    O_agent(phi). The local TDFOL parser represents agents on DeonticFormula
    objects, but formula strings used by proof gates only need a parseable
    deontic operator over phi. Preserve legacy O_t(...) predicate exports.
    """

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    normalized = _normalize_bracketed_deontic_agent_export(normalized)
    return _normalize_underscored_deontic_agent_export(normalized)


def _normalize_bracketed_deontic_agent_export(text: str) -> str:
    result: list[str] = []
    index = 0
    pattern = re.compile(r"([OPF])\s*\[\s*([^\]\(\)]+?)\s*\]\s*\(")
    while index < len(text):
        match = pattern.search(text, index)
        if match is None:
            result.append(text[index:])
            break
        open_index = match.end() - 1
        close_index = _matching_paren_index(text, open_index)
        if close_index is None:
            result.append(text[index:])
            break
        inner = _normalize_deontic_agent_annotation_export(
            text[open_index + 1:close_index]
        )
        result.append(text[index:match.start()])
        raw_formula = _formula_from_bracketed_deontic_agent(
            match.group(1),
            match.group(2),
            inner,
        )
        result.append(raw_formula or f"{match.group(1)}({inner})")
        index = close_index + 1
    return "".join(result)


def _formula_from_bracketed_deontic_agent(
    operator: str,
    agent: str,
    inner: str,
) -> str:
    """Synthesize formulas from O[agency](publish notice) style exports."""

    payload = str(inner or "").strip()
    if not payload or _looks_like_tdfol_formula(payload):
        return ""
    agent_text = re.sub(r"\s+", " ", str(agent or "")).strip()
    if not agent_text:
        return ""
    operator = str(operator or "").upper()
    modal_word = {
        "O": "shall",
        "P": "may",
        "F": "shall not",
    }.get(operator, "shall")
    return _formula_from_raw_deontic_text_argument(
        operator,
        f"{agent_text} {modal_word} {payload}",
        prefer_modal_clause=True,
    )


def _normalize_underscored_deontic_agent_export(text: str) -> str:
    result: list[str] = []
    index = 0
    pattern = re.compile(r"(?<![A-Za-z0-9_])([OPF])_([A-Za-z_][A-Za-z0-9_-]*)\s*\(")
    while index < len(text):
        match = pattern.search(text, index)
        if match is None:
            result.append(text[index:])
            break
        agent = match.group(2)
        open_index = match.end() - 1
        close_index = _matching_paren_index(text, open_index)
        if close_index is None:
            result.append(text[index:])
            break
        if agent.lower() in {"t", "time"}:
            result.append(text[index:close_index + 1])
        else:
            result.append(text[index:match.start()])
            inner = _normalize_deontic_agent_annotation_export(
                text[open_index + 1:close_index]
            )
            result.append(f"{match.group(1)}({inner})")
        index = close_index + 1
    return "".join(result)


def _unwrap_tdfol_json_export(text: str) -> str:
    """Extract formula text from JSON/JSON-ish proof obligation exports."""

    normalized = str(text or "").strip()
    if not normalized or normalized[0] not in "[{":
        return normalized
    try:
        parsed = json.loads(normalized)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        extracted = _tdfol_formula_text_from_json_value(parsed)
        if extracted:
            return extracted

    export_key_pattern = "|".join(
        re.escape(key) for key in _TDFOL_FORMULA_EXPORT_KEYS
    )
    match = re.search(
        rf"""(?is)(?:^|[,{{\s])["']?(?:{export_key_pattern})["']?\s*:\s*(["'])(.*?)\1""",
        normalized,
    )
    if match:
        return match.group(2).strip()
    return normalized


def _normalize_tdfol_export_value(value: str) -> str:
    candidate = str(value or "").strip("`\"'").strip()
    formula = _extract_balanced_tdfol_formula(candidate)
    if formula:
        return formula
    extracted = _tdfol_formula_text_from_export_payload(candidate)
    return extracted or candidate


def _tdfol_formula_text_from_export_payload(value: str) -> str:
    """Extract formula text from JSON or JSON-ish nested TDFOL view payloads."""

    candidate = str(value or "").strip()
    if not candidate:
        return ""
    unwrapped = _unwrap_tdfol_json_export(candidate)
    if unwrapped != candidate:
        return unwrapped
    formula = _extract_balanced_tdfol_formula(candidate)
    if formula:
        return formula
    return ""


def _tdfol_formula_text_from_json_value(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in _TDFOL_FORMULA_EXPORT_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
            nested = _tdfol_formula_text_from_json_value(candidate)
            if nested:
                return nested
        for candidate in value.values():
            nested = _tdfol_formula_text_from_json_value(candidate)
            if nested:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for candidate in value:
            nested = _tdfol_formula_text_from_json_value(candidate)
            if nested:
                return nested
    return ""


def _normalize_deontic_argument_export(text: str) -> str:
    """Canonicalize O(agent, action(...)) style exports to O(action(...))."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    result: list[str] = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if (
            char in {"O", "P", "F"}
            and (index == 0 or not normalized[index - 1].isalnum())
            and index + 1 < len(normalized)
            and normalized[index + 1] == "("
        ):
            close_index = _matching_paren_index(normalized, index + 1)
            if close_index is not None:
                inner = normalized[index + 2 : close_index]
                parts = _split_top_level_commas(inner)
                formula_part = _formula_argument_from_deontic_parts(parts)
                if formula_part:
                    result.append(f"{char}({formula_part})")
                    index = close_index + 1
                    continue
        result.append(char)
        index += 1
    return "".join(result)


def _normalize_raw_deontic_text_export(text: str) -> str:
    """Canonicalize raw-text deontic exports such as O(agency shall file)."""

    normalized = str(text or "").strip()
    if not normalized:
        return normalized
    result: list[str] = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if (
            char in {"O", "P", "F"}
            and (index == 0 or not normalized[index - 1].isalnum())
            and index + 1 < len(normalized)
            and normalized[index + 1] == "("
        ):
            close_index = _matching_paren_index(normalized, index + 1)
            if close_index is not None:
                inner = normalized[index + 2 : close_index].strip()
                formula = _formula_from_raw_deontic_text_argument(char, inner)
                if formula:
                    result.append(formula)
                    index = close_index + 1
                    continue
        result.append(char)
        index += 1
    return "".join(result)


def _formula_from_labeled_raw_proof_obligation(text: str) -> str:
    """Synthesize TDFOL from raw prose after proof-obligation labels."""

    candidate = str(text or "").strip().strip("`\"'").strip()
    if not candidate or _looks_like_tdfol_formula(candidate):
        return ""
    if not _looks_like_legal_text_export(candidate):
        return ""
    norm = _synthesized_norm_from_text(candidate, prefer_modal_clause=True)
    if norm is None:
        return ""
    formula = _tdfol_formula_from_norm(norm)
    return formula.to_string() if hasattr(formula, "to_string") else ""


def _formula_from_raw_deontic_text_argument(
    operator: str,
    text: str,
    *,
    prefer_modal_clause: bool = False,
) -> str:
    candidate = str(text or "").strip().rstrip(".").strip()
    if not candidate or _looks_like_tdfol_formula(candidate):
        return ""
    if not _looks_like_legal_text_obligation(candidate):
        return ""
    norm = _synthesized_norm_from_text(
        candidate,
        prefer_modal_clause=prefer_modal_clause,
    )
    if norm is None:
        return ""
    actor = _symbol(
        norm.get("actor")
        or _infer_actor_from_text(
            candidate,
            prefer_modal_clause=prefer_modal_clause,
        )
    )
    action = _predicate_name(
        norm.get("action")
        or _infer_action_from_text(
            candidate,
            prefer_modal_clause=prefer_modal_clause,
        )
    )
    return f"{operator}({action}({actor}))"


def _formula_argument_from_deontic_parts(parts: Sequence[str]) -> str:
    normalized_parts = [str(part or "").strip() for part in parts]
    for part in reversed([str(part or "").strip() for part in parts]):
        if not part:
            continue
        key_value = re.match(
            r"(?is)^(?:formula|proof_input|proof_formula|tdfol_formula|"
            r"action|predicate|event|target)\s*[:=]\s*(.+)$",
            part,
        )
        candidate = key_value.group(1).strip() if key_value else part
        candidate = candidate.strip("`\"'").strip()
        if _looks_like_tdfol_formula(candidate):
            return candidate
    raw_action_formula = _formula_from_deontic_agent_action_parts(normalized_parts)
    if raw_action_formula:
        return raw_action_formula
    return ""


def _formula_from_deontic_agent_action_parts(parts: Sequence[str]) -> str:
    """Synthesize predicate(agent) from O(agent, raw legal action text)."""

    cleaned = [
        str(part or "").strip("`\"' ").strip()
        for part in parts
        if str(part or "").strip()
    ]
    if len(cleaned) < 2:
        return ""
    actor = cleaned[0]
    action = cleaned[-1]
    if _looks_like_tdfol_formula(action):
        return ""
    if not re.search(r"[A-Za-z]", actor) or not re.search(r"[A-Za-z]", action):
        return ""
    if not (re.search(r"\s", action) or re.search(r"[-,;]", action)):
        return ""
    actor_symbol = _symbol(actor)
    action_name = _predicate_name(action)
    return f"{action_name}({actor_symbol})"


def _matching_paren_index(text: str, open_index: int) -> Optional[int]:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts


def _looks_like_tdfol_formula(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if re.match(r"^(?:forall|exists|not\b)", candidate, re.IGNORECASE):
        return True
    if re.match(r"^(?:[OPFGX]|□|◊|¬)\s*[\(\[\{]", candidate):
        return True
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*\(", candidate))


def _unwrap_tdfol_key_value_export(text: str) -> str:
    """Extract formula=... from proof-obligation key/value wrappers."""

    normalized = str(text or "").strip()
    match = re.match(
        r"^\s*(?:TDFOL(?:[\s.]prover)?|proof_obligation|proof\s+obligation|"
        r"tdfol_formula|tdfol\s+formula|obligation)\s*\(",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match or not normalized.endswith(")"):
        return normalized
    inner = normalized[match.end() : -1].strip()
    for key in _TDFOL_FORMULA_EXPORT_KEYS:
        value = _extract_tdfol_key_value(inner, key)
        if value:
            return value.strip("`\"'").strip()
    formula = _extract_balanced_tdfol_formula(inner)
    if formula:
        return formula
    return normalized


def _extract_tdfol_key_value(text: str, key: str) -> Optional[str]:
    pattern = re.compile(rf"(?i)(?:^|[,;:])\s*{re.escape(key)}\s*[:=]")
    match = pattern.search(text)
    if match is None:
        return None
    start = match.end()
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        elif char in ",;" and depth == 0:
            return text[start:index].strip()
    return text[start:].strip()


def _strip_tdfol_line_comment(text: str) -> str:
    for marker in ("#", "%"):
        index = text.find(marker)
        if index >= 0:
            return text[:index].rstrip()
    return text


def _unwrap_tdfol_export_wrapper(text: str) -> str:
    """Extract the formula argument from TPTP-style fof/tff/cnf wrappers."""

    match = re.match(r"^\s*(?:fof|tff|cnf)\s*\(", text, flags=re.IGNORECASE)
    if not match or not text.rstrip().endswith(")"):
        return text
    inner = text[match.end() :].rstrip()
    if inner.endswith("."):
        inner = inner[:-1].rstrip()
    if not inner.endswith(")"):
        return text
    inner = inner[:-1]
    parts: list[str] = []
    start = 0
    depth = 0
    for index, char in enumerate(inner):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(inner[start:index].strip())
            start = index + 1
    parts.append(inner[start:].strip())
    if len(parts) < 3:
        return text
    return parts[2].strip()


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


def _synthesized_norm_from_text(
    text: str,
    *,
    prefer_modal_clause: bool = False,
) -> Optional[dict[str, Any]]:
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text:
        return None
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:12]
    modality = _normalized_modality(normalized_text)
    use_modal_clause = prefer_modal_clause or _is_uscode_text(normalized_text)
    return {
        "action": _infer_action_from_text(
            normalized_text,
            prefer_modal_clause=use_modal_clause,
        ),
        "actor": _infer_actor_from_text(
            normalized_text,
            prefer_modal_clause=use_modal_clause,
        ),
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


def _infer_action_from_text(text: str, *, prefer_modal_clause: bool = False) -> str:
    normalized = " ".join(str(text or "").split())
    lowered = normalized.lower()
    if re.search(r"\b(?:repealed|repeal)\b", lowered):
        return "statute_status_repealed"
    if re.search(r"\bomitted\b", lowered):
        return "statute_status_omitted"
    definition_match = re.search(
        r"(?:^|\bdefinitions?\b.*?)[\"']?([a-z][a-z0-9_-]{1,80})[\"']?\s+means\b",
        lowered,
    )
    if definition_match:
        return f"define_{definition_match.group(1)}"
    if prefer_modal_clause:
        modal_action = _infer_modal_action_from_text(normalized)
        if modal_action:
            return modal_action
    uscode_heading = _infer_uscode_heading_action(normalized)
    if uscode_heading:
        return uscode_heading
    tokens = re.findall(r"[a-z0-9]+", lowered)
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


def _infer_modal_action_from_text(text: str) -> str:
    """Extract the operative action from the first shall/must/may clause."""

    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    match = re.search(
        r"\b(?:shall|must|may)\s+(?:not\s+)?(.+?)(?:[.;]|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    action = match.group(1).strip()
    action = re.sub(
        r"\b(?:as|if|when|unless|before|after|until|except)\b.*$",
        "",
        action,
        flags=re.IGNORECASE,
    ).strip(" ,")
    return action


def _infer_uscode_heading_action(text: str) -> str:
    """Extract a compact fallback predicate from U.S. Code citation headings."""

    normalized = " ".join(str(text or "").split())
    if not normalized or not re.search(
        r"U\.?\s*S\.?\s*C\.?",
        normalized,
        re.IGNORECASE,
    ):
        return ""

    sec_match = re.search(
        r"\bSecs?\.\s+[0-9A-Za-z.\-]+(?:\s+to\s+[0-9A-Za-z.\-]+)?\s+-\s+"
        r"(.+?)(?=\s+(?:From the U\.S\. Government|§|Editorial Notes|"
        r"Statutory Notes|Historical and Revision Notes|Pub\. L\.|"
        r"\([A-Z][a-z]{2}\.|[A-Z][a-z]+\s+[0-9]{1,2},\s+[0-9]{4})|$)",
        normalized,
        flags=re.IGNORECASE,
    )
    if sec_match:
        heading = _clean_uscode_heading_phrase(sec_match.group(1))
        if heading:
            return heading

    uppercase_tail = ""
    for match in re.finditer(
        r"(?:SUBCHAPTER|CHAPTER|PART|Subtitle)\s+[A-Z0-9IVXLCDM.\-]+\s+-\s+"
        r"([A-Z][A-Z0-9,.;:'()&/\-\s]{4,120})(?=\s+(?:Sec\.|Secs?\.)|$)",
        normalized,
    ):
        uppercase_tail = match.group(1)
    if uppercase_tail:
        heading = _clean_uscode_heading_phrase(uppercase_tail)
        if heading:
            return heading

    return ""


def _clean_uscode_heading_phrase(text: str) -> str:
    heading = re.sub(r"\s+", " ", str(text or "")).strip(" -.;:")
    if not heading:
        return ""
    nested_heading = re.split(
        r"\b(?:SUBCHAPTER|CHAPTER|PART|Subtitle)\s+"
        r"[A-Z0-9IVXLCDM.\-]+\s+-\s+",
        heading,
        flags=re.IGNORECASE,
    )
    if len(nested_heading) > 1:
        heading = nested_heading[-1].strip(" -.;:")
    heading = re.sub(r"\b(?:From the U\.S\. Government.*)$", "", heading).strip(" -.;:")
    heading = re.sub(
        r"\b(?:U\.?\s*S\.?\s*C\.?|United States Code)\b",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    heading = re.sub(
        r"\b(?:Title|Edition|Chapter|Subchapter|Subtitle|Part)\b",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    heading = re.sub(r"\s+", " ", heading).strip(" -.;:")
    if not heading:
        return ""
    return heading.lower()


def _infer_actor_from_text(text: str, *, prefer_modal_clause: bool = False) -> str:
    text_value = " ".join(str(text or "").split())
    if prefer_modal_clause:
        modal_subject = _infer_modal_actor_from_text(text_value)
        if modal_subject:
            return modal_subject
    lowered = text_value.lower()
    ignored = {"term", "section", "subsection", "chapter", "title", "part", "clause"}
    for match in re.finditer(r"\bthe\s+([a-z][a-z0-9_]*)\b", lowered):
        candidate = match.group(1).strip()
        if candidate and candidate not in ignored:
            return candidate
    return "actor"


def _is_uscode_text(text: str) -> bool:
    return bool(
        re.search(
            r"(?:\b[0-9]+\s+U\.?\s*S\.?\s*C\.?\b|\bUnited States Code\b|\bSec\.)",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )


def _infer_modal_actor_from_text(text: str) -> str:
    """Extract the legal subject immediately governing shall/must/may clauses."""

    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    matches = list(
        re.finditer(
            r"\b(?:the\s+)?([A-Za-z][A-Za-z0-9'&/().,\-\s]{1,120}?)\s+"
            r"(?:shall|must|may)\b",
            normalized,
        )
    )
    for match in reversed(matches):
        subject = _clean_modal_actor_subject(match.group(1))
        if subject:
            return subject
    return ""


def _clean_modal_actor_subject(text: str) -> str:
    """Trim citation and heading text from a modal-clause subject."""

    subject = re.sub(r"\s+", " ", str(text or "")).strip(" ,;:-")
    if not subject:
        return ""
    subject = re.split(
        r"\b(?:Sec\.|Secs?\.|Section|CHAPTER|SUBCHAPTER|PART|Subtitle|Title)\b",
        subject,
        flags=re.IGNORECASE,
    )[-1].strip(" ,;:-")
    sentence_parts = re.split(
        r"(?<=[.;])\s+(?=(?:The|Each|Any|No|A|An|Such|Every)\b)",
        subject,
        flags=re.IGNORECASE,
    )
    subject = sentence_parts[-1].strip(" ,;:-")
    heading_parts = re.split(
        r"\s+-\s+(?=(?:The|Each|Any|No|A|An|Such|Every)\b)",
        subject,
        flags=re.IGNORECASE,
    )
    subject = heading_parts[-1].strip(" ,;:-")
    subject = re.sub(r"^the\s+", "", subject, flags=re.IGNORECASE).strip()
    return subject


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
