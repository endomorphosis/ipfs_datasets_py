"""FOL/TDFOL implementation of the legal IR bridge contract."""

from __future__ import annotations

import hashlib
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

        norms = _deontic_norms_from_text(text, converter=self._converter())
        resolved_document_id = document_id or _document_id("tdfol", text)
        formula_records = _tdfol_formula_records(norms)
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
                },
            ),
            {
                "formula_records": formula_records,
                "graph_data": graph_data,
                "norms": norms,
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


def _deontic_norms_from_text(text: str, *, converter: Any) -> list[dict[str, Any]]:
    result = converter.convert(text)
    metadata = dict(getattr(result, "metadata", {}) or {})
    return _list_of_dicts(metadata.get("legal_norm_irs"))


def _tdfol_formula_records(norms: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, norm in enumerate(norms):
        formula = _tdfol_formula_from_norm(norm)
        formula_text = formula.to_string()
        parse_ok = _tdfol_parse_ok(formula_text)
        records.append(
            {
                "formula": formula_text,
                "formula_object": formula,
                "parse_ok": parse_ok,
                "predicates": sorted(formula.get_predicates()),
                "source_id": str(norm.get("source_id") or f"tdfol:norm:{index}"),
                "source_norm": dict(norm),
            }
        )
    return records


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


def _tdfol_parse_ok(formula: str) -> bool:
    try:
        from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol_safe

        return parse_tdfol_safe(formula) is not None
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
        return f"n_{name}"
    return name


def _symbol(value: Any) -> str:
    symbol = _predicate_name(value)
    if symbol == "act":
        return "actor"
    return symbol


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


__all__ = ["FolTdfolBridgeAdapter"]
