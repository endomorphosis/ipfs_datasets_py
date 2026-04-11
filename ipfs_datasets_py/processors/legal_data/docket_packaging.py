"""Parquet and CAR packaging helpers for docket datasets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from ..serialization.car_conversion import DataInterchangeUtils
from ..storage.ipld.storage import IPLDStorage
from ..retrieval import bm25_search_documents, embed_query_for_backend, hashed_term_projection, vector_dot
from ..legal_scrapers.canonical_legal_corpora import get_canonical_legal_corpus


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_document_attachments(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    for index, document in enumerate(documents, start=1):
        document_id = str(document.get("document_id") or document.get("id") or f"document_{index}")
        metadata = dict(document.get("metadata") or {})
        raw = dict(metadata.get("raw") or {})
        candidates: List[Any] = []
        for key in ("attachments", "attachment_paths", "sidecar_paths", "exhibits", "files"):
            values = raw.get(key)
            if isinstance(values, list):
                candidates.extend(values)
        source_path = raw.get("source_path") or metadata.get("source_path")
        if source_path:
            candidates.append(source_path)
        for attachment_index, candidate in enumerate(candidates, start=1):
            if isinstance(candidate, dict):
                label = str(candidate.get("title") or candidate.get("label") or candidate.get("path") or candidate.get("url") or f"attachment_{attachment_index}")
                path_or_url = str(candidate.get("path") or candidate.get("url") or candidate.get("source") or "")
                attachment_type = str(candidate.get("type") or candidate.get("mime_type") or "")
                attachment_metadata = dict(candidate)
            else:
                label = str(candidate)
                path_or_url = str(candidate)
                attachment_type = ""
                attachment_metadata = {}
            attachments.append(
                {
                    "attachment_id": f"{document_id}_attachment_{attachment_index}",
                    "document_id": document_id,
                    "label": label,
                    "path_or_url": path_or_url,
                    "attachment_type": attachment_type,
                    "metadata_json": json.dumps(_jsonable(attachment_metadata), sort_keys=True),
                }
            )
    return attachments


def _flatten_mapping_rows(
    payload: Mapping[str, Any],
    *,
    row_id_field: str,
    value_field: str = "payload_json",
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key, value in payload.items():
        rows.append(
            {
                row_id_field: str(key),
                value_field: json.dumps(_jsonable(value), sort_keys=True),
            }
        )
    return rows


def _write_rows_to_parquet(rows: Sequence[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_rows = [_normalize_parquet_row(row) for row in rows] if rows else [{"_empty": True}]
    table = pa.Table.from_pylist(normalized_rows)
    pq.write_table(table, output_path)
    return {
        "row_count": 0 if rows == [] else len(rows),
        "schema": [{"name": field.name, "type": str(field.type)} for field in table.schema],
    }


def _normalize_parquet_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, Mapping):
            normalized[str(key)] = json.dumps(_jsonable(value), sort_keys=True)
        elif isinstance(value, (list, tuple, set)):
            normalized[str(key)] = json.dumps(_jsonable(value), sort_keys=True)
        else:
            normalized[str(key)] = value
    return normalized


def _parse_json_list_field(value: Any) -> List[Any]:
    if isinstance(value, list):
        return list(value)
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _build_packaged_inspection_payload(
    *,
    dataset_id: Any,
    docket_id: Any,
    case_name: Any,
    court: Any,
    document_count: int,
    attachment_count: int,
    latest_proof_packet_id: Any,
    latest_proof_packet_version: Any,
    latest_routing_explanation: Mapping[str, Any] | None,
    routing_provenance: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    latest_routing = dict(latest_routing_explanation or {})
    routing_provenance_dict = dict(routing_provenance or {})
    routing_evidence = list(latest_routing.get("routing_evidence") or [])
    top_routing_evidence = dict((routing_evidence or [{}])[0])
    return {
        "dataset_id": str(dataset_id or ""),
        "docket_id": str(docket_id or ""),
        "case_name": str(case_name or ""),
        "court": str(court or ""),
        "document_count": int(document_count or 0),
        "attachment_count": int(attachment_count or 0),
        "latest_proof_packet_id": str(latest_proof_packet_id or ""),
        "latest_proof_packet_version": int(latest_proof_packet_version or 0),
        "latest_routing_reason": str(latest_routing.get("routing_reason") or ""),
        "preferred_corpus_priority": list(latest_routing.get("preferred_corpus_priority") or []),
        "preferred_state_codes": list(latest_routing.get("preferred_state_codes") or []),
        "routing_evidence_count": len(routing_evidence),
        "top_routing_citation": str(top_routing_evidence.get("citation_text") or ""),
        "top_routing_source_url": str(top_routing_evidence.get("source_url") or ""),
        "routing_provenance_piece_present": bool(routing_provenance_dict),
        "routing_provenance": routing_provenance_dict,
    }


def _parse_packaged_inspection_report_row(row: Mapping[str, Any] | None) -> Dict[str, Any]:
    report_row = dict(row or {})
    report_json = str(report_row.get("report_json") or "").strip()
    if not report_json:
        return {}
    try:
        parsed = json.loads(report_json)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def _normalize_packaged_inspection_report_row(row: Mapping[str, Any] | None) -> Dict[str, Any]:
    report_row = dict(row or {})
    if not report_row or "_empty" in report_row:
        return {}
    return {
        "report_json": str(report_row.get("report_json") or ""),
        "report_text": str(report_row.get("report_text") or ""),
        "report_markdown": str(report_row.get("report_markdown") or ""),
        "inspection": _parse_packaged_inspection_report_row(report_row),
    }


@dataclass
class DocketPackagePiece:
    piece_id: str
    parquet_path: str
    row_count: int
    group: str
    schema: List[Dict[str, Any]]
    depends_on: List[str]
    car_path: str = ""
    root_cid: str = ""
    sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "piece_id": self.piece_id,
            "parquet_path": self.parquet_path,
            "row_count": self.row_count,
            "group": self.group,
            "schema": list(self.schema),
            "depends_on": list(self.depends_on),
            "car_path": self.car_path,
            "root_cid": self.root_cid,
            "sha256": self.sha256,
        }


@dataclass
class PackagedQueryExecutionPlan:
    """A manifest-aware loading plan for a packaged docket query."""

    query: str
    strategy: str
    target: str
    piece_ids: List[str]
    rationale: str
    priority: int = 0
    estimated_cost: int = 0
    piece_costs: Dict[str, int] | None = None
    stages: List[Dict[str, Any]] | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "target": self.target,
            "piece_ids": list(self.piece_ids),
            "rationale": self.rationale,
            "priority": int(self.priority),
            "estimated_cost": int(self.estimated_cost),
            "piece_costs": dict(self.piece_costs or {}),
            "stages": [_jsonable(stage) for stage in list(self.stages or [])],
        }


class DocketDatasetPackager:
    """Package docket datasets into chain-loadable Parquet and CAR artifacts."""

    def __init__(self) -> None:
        self._car_utils = DataInterchangeUtils(storage=IPLDStorage())
        self._temp_bundle_dirs: Dict[str, tempfile.TemporaryDirectory[str]] = {}
        self._temp_piece_dirs: Dict[str, tempfile.TemporaryDirectory[str]] = {}

    def package(
        self,
        dataset: Any,
        output_dir: str | Path,
        *,
        package_name: str | None = None,
        include_car: bool = True,
    ) -> Dict[str, Any]:
        dataset_payload = dataset.to_dict() if hasattr(dataset, "to_dict") else dict(dataset)
        output_root = Path(output_dir)
        bundle_name = package_name or str(dataset_payload.get("dataset_id") or "docket_dataset_bundle")
        legacy_layout = package_name is None
        bundle_dir = output_root if legacy_layout else output_root / _safe_identifier(bundle_name)
        parquet_dir = bundle_dir if legacy_layout else bundle_dir / "parquet"
        car_dir = bundle_dir if legacy_layout else bundle_dir / "car"
        parquet_dir.mkdir(parents=True, exist_ok=True)
        if include_car:
            car_dir.mkdir(parents=True, exist_ok=True)

        documents = [dict(item) for item in list(dataset_payload.get("documents") or []) if isinstance(item, dict)]
        attachments = _extract_document_attachments(documents)
        knowledge_graph = dict(dataset_payload.get("knowledge_graph") or {})
        deontic_graph = dict(dataset_payload.get("deontic_graph") or {})
        deontic_triggers = dict(dataset_payload.get("deontic_triggers") or {})
        proof_assistant = dict(dataset_payload.get("proof_assistant") or {})
        tactician = dict(proof_assistant.get("tactician") or {})
        proof_store = dict(proof_assistant.get("proof_store") or {})
        proof_assistant_metadata = dict(proof_assistant.get("metadata") or {})
        proof_assistant_summary = dict(proof_assistant.get("summary") or {})
        dataset_metadata = dict(dataset_payload.get("metadata") or {})
        latest_routing_explanation = dict(
            dataset_metadata.get("latest_proof_packet_routing_explanation")
            or proof_assistant_metadata.get("latest_proof_packet_routing_explanation")
            or {}
        )
        temporal_fol = dict(
            proof_assistant.get("temporal_fol")
            or proof_assistant.get("deontic_temporal_first_order_logic")
            or {}
        )
        dcec = dict(proof_assistant.get("deontic_cognitive_event_calculus") or {})
        frame_logic = dict(proof_assistant.get("frame_logic") or proof_assistant.get("frames") or {})
        proof_knowledge_graph = dict(proof_assistant.get("knowledge_graph") or {})

        temporal_formula_rows = [
            {"formula_id": f"temporal_{index}", "formula": str(formula)}
            for index, formula in enumerate(list(temporal_fol.get("formulas") or []), start=1)
            if str(formula).strip()
        ]
        dcec_formula_rows = [
            {"formula_id": f"dcec_{index}", "formula": str(formula)}
            for index, formula in enumerate(list(dcec.get("formulas") or []), start=1)
            if str(formula).strip()
        ]
        frame_rows = [
            dict(frame)
            for frame in list(frame_logic.values() if isinstance(frame_logic, Mapping) else frame_logic)
            if isinstance(frame, Mapping)
        ]
        routing_provenance_row = (
            {
                "routing_reason": str(latest_routing_explanation.get("routing_reason") or ""),
                "routing_evidence_json": json.dumps(
                    _jsonable(latest_routing_explanation.get("routing_evidence") or []),
                    sort_keys=True,
                ),
                "preferred_corpus_keys_json": json.dumps(
                    _jsonable(latest_routing_explanation.get("preferred_corpus_keys") or []),
                    sort_keys=True,
                ),
                "preferred_corpus_priority_json": json.dumps(
                    _jsonable(latest_routing_explanation.get("preferred_corpus_priority") or []),
                    sort_keys=True,
                ),
                "preferred_dataset_ids_json": json.dumps(
                    _jsonable(latest_routing_explanation.get("preferred_dataset_ids") or []),
                    sort_keys=True,
                ),
                "preferred_dataset_priority_json": json.dumps(
                    _jsonable(latest_routing_explanation.get("preferred_dataset_priority") or []),
                    sort_keys=True,
                ),
                "preferred_state_codes_json": json.dumps(
                    _jsonable(latest_routing_explanation.get("preferred_state_codes") or []),
                    sort_keys=True,
                ),
                "authority_backed": bool(latest_routing_explanation.get("authority_backed")),
            }
            if latest_routing_explanation
            else {}
        )
        inspection_payload = _build_packaged_inspection_payload(
            dataset_id=dataset_payload.get("dataset_id"),
            docket_id=dataset_payload.get("docket_id"),
            case_name=dataset_payload.get("case_name"),
            court=dataset_payload.get("court"),
            document_count=len(documents),
            attachment_count=len(attachments),
            latest_proof_packet_id=dataset_metadata.get("latest_proof_packet_id")
            or proof_assistant_metadata.get("latest_proof_packet_id"),
            latest_proof_packet_version=dataset_metadata.get("latest_proof_packet_version")
            or proof_assistant_metadata.get("latest_proof_packet_version"),
            latest_routing_explanation=latest_routing_explanation,
            routing_provenance=routing_provenance_row,
        )
        inspection_report_json = json.dumps(inspection_payload, indent=2, ensure_ascii=False)
        inspection_report_text = self.render_packaged_inspection_report_from_inspection(
            inspection_payload,
            report_format="text",
        )
        inspection_report_markdown = self.render_packaged_inspection_report_from_inspection(
            inspection_payload,
            report_format="markdown",
        )

        section_rows: List[tuple[str, str, List[Dict[str, Any]], List[str]]] = [
            (
                "dataset_core",
                "dataset",
                [
                    {
                        "dataset_id": str(dataset_payload.get("dataset_id") or ""),
                        "docket_id": str(dataset_payload.get("docket_id") or ""),
                        "case_name": str(dataset_payload.get("case_name") or ""),
                        "court": str(dataset_payload.get("court") or ""),
                        "metadata_json": json.dumps(_jsonable(dataset_payload.get("metadata") or {}), sort_keys=True),
                    }
                ],
                [],
            ),
            ("documents", "documents", documents, ["dataset_core"]),
            ("attachments", "attachments", attachments, ["documents"]),
            (
                "plaintiff_docket",
                "docket_sidecars",
                [dict(item) for item in list(dataset_payload.get("plaintiff_docket") or []) if isinstance(item, dict)],
                ["dataset_core"],
            ),
            (
                "defendant_docket",
                "docket_sidecars",
                [dict(item) for item in list(dataset_payload.get("defendant_docket") or []) if isinstance(item, dict)],
                ["dataset_core"],
            ),
            (
                "authorities",
                "docket_sidecars",
                [dict(item) for item in list(dataset_payload.get("authorities") or []) if isinstance(item, dict)],
                ["dataset_core"],
            ),
            ("knowledge_graph_entities", "knowledge_graph", list(knowledge_graph.get("entities") or []), ["dataset_core"]),
            (
                "knowledge_graph_relationships",
                "knowledge_graph",
                list(knowledge_graph.get("relationships") or []),
                ["knowledge_graph_entities"],
            ),
            ("deontic_nodes", "deontic_graph", _flatten_mapping_rows(dict(deontic_graph.get("nodes") or {}), row_id_field="node_id"), ["dataset_core"]),
            ("deontic_rules", "deontic_graph", _flatten_mapping_rows(dict(deontic_graph.get("rules") or {}), row_id_field="rule_id"), ["deontic_nodes"]),
            (
                "deontic_trigger_entries",
                "deontic_graph",
                [dict(item) for item in list(deontic_triggers.get("entries") or []) if isinstance(item, dict)],
                ["deontic_rules"],
            ),
            (
                "proof_agenda",
                "proof_assistant",
                [dict(item) for item in list(proof_assistant.get("agenda") or []) if isinstance(item, dict)],
                ["deontic_trigger_entries"],
            ),
            (
                "proof_tactician_plans",
                "proof_assistant",
                [dict(item) for item in list(tactician.get("plans") or []) if isinstance(item, dict)],
                ["proof_agenda"],
            ),
            (
                "proof_evidence_packets",
                "proof_assistant",
                [dict(item) for item in list(proof_assistant.get("evidence_packets") or []) if isinstance(item, dict)],
                ["proof_tactician_plans"],
            ),
            (
                "proof_store_entries",
                "proof_assistant",
                _flatten_mapping_rows(
                    {
                        str(key): value
                        for key, value in dict(proof_store.get("proofs") or {}).items()
                        if str(key).strip()
                    },
                    row_id_field="proof_id",
                ),
                ["proof_evidence_packets"],
            ),
            (
                "proof_store_certificates",
                "proof_assistant",
                [dict(item) for item in list(proof_store.get("certificates") or []) if isinstance(item, dict)],
                ["proof_store_entries"],
            ),
            (
                "proof_assistant_metadata",
                "proof_assistant",
                [
                    {
                        "metadata_json": json.dumps(_jsonable(proof_assistant_metadata), sort_keys=True),
                        "summary_json": json.dumps(_jsonable(proof_assistant_summary), sort_keys=True),
                    }
                ] if proof_assistant_metadata or proof_assistant_summary else [],
                ["proof_store_certificates"],
            ),
            (
                "routing_provenance",
                "provenance",
                [routing_provenance_row] if routing_provenance_row else [],
                ["proof_assistant_metadata"],
            ),
            (
                "inspection_report",
                "provenance",
                [
                    {
                        "report_json": inspection_report_json,
                        "report_text": inspection_report_text,
                        "report_markdown": inspection_report_markdown,
                    }
                ],
                ["routing_provenance"],
            ),
            (
                "temporal_formulas",
                "proof_assistant",
                temporal_formula_rows,
                ["inspection_report"],
            ),
            (
                "dcec_formulas",
                "proof_assistant",
                dcec_formula_rows,
                ["temporal_formulas"],
            ),
            (
                "frame_logic_frames",
                "proof_assistant",
                frame_rows,
                ["dcec_formulas"],
            ),
            (
                "proof_knowledge_graph_entities",
                "proof_assistant",
                [dict(item) for item in list(proof_knowledge_graph.get("entities") or []) if isinstance(item, dict)],
                ["frame_logic_frames"],
            ),
            (
                "proof_knowledge_graph_relationships",
                "proof_assistant",
                [dict(item) for item in list(proof_knowledge_graph.get("relationships") or []) if isinstance(item, dict)],
                ["proof_knowledge_graph_entities"],
            ),
            (
                "bm25_documents",
                "search_indices",
                [dict(item) for item in list((dataset_payload.get("bm25_index") or {}).get("documents") or []) if isinstance(item, dict)],
                ["documents"],
            ),
            (
                "vector_items",
                "search_indices",
                [dict(item) for item in list((dataset_payload.get("vector_index") or {}).get("items") or []) if isinstance(item, dict)],
                ["documents"],
            ),
        ]

        pieces: List[DocketPackagePiece] = []
        for piece_id, group, rows, depends_on in section_rows:
            parquet_path = parquet_dir / f"{piece_id}.parquet"
            write_meta = _write_rows_to_parquet(rows, parquet_path)
            piece = DocketPackagePiece(
                piece_id=piece_id,
                parquet_path=str(parquet_path.relative_to(bundle_dir)),
                row_count=int(write_meta["row_count"]),
                group=group,
                schema=list(write_meta["schema"]),
                depends_on=list(depends_on),
                sha256=_digest_file(parquet_path),
            )
            if include_car:
                car_path = car_dir / f"{piece_id}.car"
                piece.root_cid = str(
                    self._car_utils.parquet_to_car(
                        str(parquet_path),
                        str(car_path),
                    )
                )
                piece.car_path = str(car_path.relative_to(bundle_dir))
            pieces.append(piece)

        component_aliases: List[Dict[str, Any]] = []
        for index, piece in enumerate(pieces):
            previous_cid = pieces[index - 1].root_cid if index > 0 else ""
            next_cid = pieces[index + 1].root_cid if index + 1 < len(pieces) else ""
            component_aliases.append(
                {
                    "component_name": piece.piece_id,
                    "record_count": piece.row_count,
                    "parquet_path": piece.parquet_path,
                    "car_path": piece.car_path,
                    "cid": piece.root_cid,
                    "previous_cid": previous_cid,
                    "next_cid": next_cid,
                    "group": piece.group,
                    "depends_on": list(piece.depends_on),
                    "sha256": piece.sha256,
                }
            )

        manifest = {
            "bundle_name": bundle_name,
            "dataset_id": str(dataset_payload.get("dataset_id") or ""),
            "docket_id": str(dataset_payload.get("docket_id") or ""),
            "case_name": str(dataset_payload.get("case_name") or ""),
            "court": str(dataset_payload.get("court") or ""),
            "piece_count": len(pieces),
            "parquet_enabled": True,
            "car_enabled": include_car,
            "root_piece_id": "dataset_core",
            "chain_load_order": [piece.piece_id for piece in pieces],
            "pieces": [piece.to_dict() for piece in pieces],
            "root_cid": component_aliases[0]["cid"] if component_aliases else "",
            "tail_cid": component_aliases[-1]["cid"] if component_aliases else "",
            "component_count": len(component_aliases),
            "components": component_aliases,
            "summary": {
                "document_count": len(documents),
                "attachment_count": len(attachments),
                "knowledge_graph_entity_count": len(list(knowledge_graph.get("entities") or [])),
                "knowledge_graph_relationship_count": len(list(knowledge_graph.get("relationships") or [])),
                "deontic_rule_count": len(list((deontic_graph.get("rules") or {}).keys())),
                "proof_agenda_count": len(list(proof_assistant.get("agenda") or [])),
                "tactician_plan_count": len(list(tactician.get("plans") or [])),
                "proof_packet_count": len(list(proof_assistant.get("evidence_packets") or [])),
                "proof_store_count": len(list((proof_store.get("proofs") or {}).keys())),
            },
            "provenance": {
                "latest_proof_packet_routing_explanation": _jsonable(latest_routing_explanation),
                "has_latest_proof_packet_routing_explanation": bool(latest_routing_explanation),
            },
        }

        manifest_json_path = bundle_dir / ("manifest.json" if legacy_layout else "bundle_manifest.json")
        manifest_json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        manifest_parquet_path = parquet_dir / ("manifest.parquet" if legacy_layout else "bundle_manifest.parquet")
        _write_rows_to_parquet(
            [
                {
                    "bundle_name": bundle_name,
                    "dataset_id": manifest["dataset_id"],
                    "docket_id": manifest["docket_id"],
                    "root_piece_id": manifest["root_piece_id"],
                    "manifest_json": json.dumps(_jsonable(manifest), sort_keys=True),
                }
            ],
            manifest_parquet_path,
        )

        manifest_car_path = ""
        manifest_root_cid = ""
        if include_car:
            manifest_car = car_dir / ("manifest.car" if legacy_layout else "bundle_manifest.car")
            manifest_root_cid = str(self._car_utils.parquet_to_car(str(manifest_parquet_path), str(manifest_car)))
            manifest_car_path = str(manifest_car.relative_to(bundle_dir))
            manifest["manifest_root_cid"] = manifest_root_cid
            manifest["manifest_car_path"] = manifest_car_path
            manifest_json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return {
            "bundle_dir": str(bundle_dir),
            "manifest_json_path": str(manifest_json_path),
            "manifest_parquet_path": str(manifest_parquet_path),
            "manifest_car_path": str(bundle_dir / manifest_car_path) if manifest_car_path else "",
            "manifest_root_cid": manifest_root_cid,
            "piece_count": len(pieces),
            "pieces": [piece.to_dict() for piece in pieces],
            "summary": dict(manifest["summary"]),
        }

    def load_package(self, manifest_path: str | Path) -> Dict[str, Any]:
        bundle_dir, manifest = self._resolve_manifest(manifest_path)
        rows_by_piece = self.load_package_components(bundle_dir, manifest=manifest)
        return self._rebuild_dataset(manifest, rows_by_piece)

    def load_package_components(
        self,
        manifest_path: str | Path,
        *,
        piece_ids: Optional[Sequence[str]] = None,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        bundle_dir, resolved_manifest = self._resolve_manifest(manifest_path, manifest=manifest)
        requested = {str(piece_id) for piece_id in list(piece_ids or []) if str(piece_id).strip()}
        rows_by_piece: Dict[str, List[Dict[str, Any]]] = {}
        for piece in list(resolved_manifest.get("pieces") or []):
            piece_id = str(piece.get("piece_id") or "")
            if requested and piece_id not in requested:
                continue
            parquet_path = self._resolve_piece_parquet_path(bundle_dir, piece)
            if parquet_path is None or not parquet_path.exists():
                continue
            table = pq.read_table(parquet_path)
            rows = table.to_pylist()
            rows_by_piece[piece_id] = [] if rows == [{"_empty": True}] else rows
        return rows_by_piece

    def load_package_piece(
        self,
        manifest_path: str | Path,
        piece_id: str,
        *,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        rows_by_piece = self.load_package_components(
            manifest_path,
            piece_ids=[piece_id],
            manifest=manifest,
        )
        return list(rows_by_piece.get(str(piece_id) or "", []))

    def iter_piece_chain(self, manifest_path: str | Path) -> List[Dict[str, Any]]:
        _, manifest = self._resolve_manifest(manifest_path)
        ordered: List[Dict[str, Any]] = []
        piece_map = {
            str(piece.get("piece_id") or ""): dict(piece)
            for piece in list(manifest.get("pieces") or [])
            if str(piece.get("piece_id") or "")
        }
        for piece_id in list(manifest.get("chain_load_order") or []):
            piece = piece_map.get(str(piece_id) or "")
            if piece is not None:
                ordered.append(piece)
        if ordered:
            return ordered
        return [dict(piece) for piece in list(manifest.get("pieces") or [])]

    def load_minimal_dataset_view(self, manifest_path: str | Path) -> Dict[str, Any]:
        bundle_dir, manifest = self._resolve_manifest(manifest_path)
        rows_by_piece = self.load_package_components(
            bundle_dir,
            piece_ids=["dataset_core", "documents", "attachments", "routing_provenance", "inspection_report"],
            manifest=manifest,
        )
        dataset_core = dict((rows_by_piece.get("dataset_core") or [{}])[0])
        routing_provenance = dict((rows_by_piece.get("routing_provenance") or [{}])[0])
        inspection_report = dict((rows_by_piece.get("inspection_report") or [{}])[0])
        return {
            "dataset_id": str(dataset_core.get("dataset_id") or manifest.get("dataset_id") or ""),
            "docket_id": str(dataset_core.get("docket_id") or manifest.get("docket_id") or ""),
            "case_name": str(dataset_core.get("case_name") or manifest.get("case_name") or ""),
            "court": str(dataset_core.get("court") or manifest.get("court") or ""),
            "documents": self._restore_rows(rows_by_piece.get("documents")),
            "attachments": self._restore_rows(rows_by_piece.get("attachments")),
            "routing_provenance": routing_provenance if routing_provenance and "_empty" not in routing_provenance else {},
            "inspection_report": _normalize_packaged_inspection_report_row(inspection_report),
            "package_manifest": dict(manifest),
        }

    def load_summary_view(self, manifest_path: str | Path) -> Dict[str, Any]:
        bundle_dir, manifest = self._resolve_manifest(manifest_path)
        rows_by_piece = self.load_package_components(
            bundle_dir,
            piece_ids=["dataset_core", "routing_provenance", "inspection_report"],
            manifest=manifest,
        )
        dataset_core = dict((rows_by_piece.get("dataset_core") or [{}])[0])
        routing_provenance = dict((rows_by_piece.get("routing_provenance") or [{}])[0])
        inspection_report = dict((rows_by_piece.get("inspection_report") or [{}])[0])
        manifest_summary = dict(manifest.get("summary") or {})
        return {
            "dataset_id": str(dataset_core.get("dataset_id") or manifest.get("dataset_id") or ""),
            "docket_id": str(dataset_core.get("docket_id") or manifest.get("docket_id") or ""),
            "case_name": str(dataset_core.get("case_name") or manifest.get("case_name") or ""),
            "court": str(dataset_core.get("court") or manifest.get("court") or ""),
            "document_count": int(manifest_summary.get("document_count") or 0),
            "attachment_count": int(manifest_summary.get("attachment_count") or 0),
            "routing_provenance": routing_provenance if routing_provenance and "_empty" not in routing_provenance else {},
            "inspection_report": _normalize_packaged_inspection_report_row(inspection_report),
            "package_manifest": dict(manifest),
        }

    def load_inspection_report(
        self,
        manifest_path: str | Path,
        *,
        report_format: str = "parsed",
    ) -> Any:
        minimal_view = self.load_minimal_dataset_view(manifest_path)
        inspection_report = dict(minimal_view.get("inspection_report") or {})
        normalized_format = str(report_format or "parsed").strip().lower()
        if normalized_format in {"parsed", "dict", "inspection"}:
            return dict(inspection_report.get("inspection") or {})
        if normalized_format == "json":
            return str(inspection_report.get("report_json") or "")
        if normalized_format == "text":
            return str(inspection_report.get("report_text") or "")
        if normalized_format == "markdown":
            return str(inspection_report.get("report_markdown") or "")
        if normalized_format == "row":
            return inspection_report
        raise ValueError(f"Unsupported inspection report format: {report_format}")

    def inspect_packaged_bundle(self, manifest_path: str | Path) -> Dict[str, Any]:
        summary_view = self.load_summary_view(manifest_path)
        archived_report = _parse_packaged_inspection_report_row(summary_view.get("inspection_report"))
        if archived_report:
            archived_report["routing_provenance_piece_present"] = bool(summary_view.get("routing_provenance"))
            if "routing_provenance" not in archived_report:
                archived_report["routing_provenance"] = dict(summary_view.get("routing_provenance") or {})
            return archived_report
        manifest = dict(summary_view.get("package_manifest") or {})
        routing_provenance = dict(summary_view.get("routing_provenance") or {})
        latest_routing = dict(
            manifest.get("provenance", {}).get("latest_proof_packet_routing_explanation")
            or {}
        )
        return _build_packaged_inspection_payload(
            dataset_id=summary_view.get("dataset_id"),
            docket_id=summary_view.get("docket_id"),
            case_name=summary_view.get("case_name"),
            court=summary_view.get("court"),
            document_count=int(summary_view.get("document_count") or 0),
            attachment_count=int(summary_view.get("attachment_count") or 0),
            latest_proof_packet_id=(manifest.get("metadata") or {}).get("latest_proof_packet_id"),
            latest_proof_packet_version=(manifest.get("metadata") or {}).get("latest_proof_packet_version"),
            latest_routing_explanation=latest_routing,
            routing_provenance=routing_provenance,
        )

    def render_packaged_inspection_report_from_inspection(
        self,
        inspection: Mapping[str, Any],
        *,
        report_format: str = "markdown",
    ) -> str:
        inspection_dict = dict(inspection or {})
        normalized_format = str(report_format or "markdown").strip().lower()
        if normalized_format == "json":
            return json.dumps(inspection_dict, indent=2, ensure_ascii=False) + "\n"

        routing_provenance = dict(inspection_dict.get("routing_provenance") or {})
        preferred_corpus_priority = list(inspection_dict.get("preferred_corpus_priority") or [])
        preferred_state_codes = list(inspection_dict.get("preferred_state_codes") or [])
        routing_evidence = _parse_json_list_field(routing_provenance.get("routing_evidence_json"))
        top_routing = dict((routing_evidence or [{}])[0])

        lines = [
            "Packaged Docket Provenance Report",
            f"Dataset ID: {inspection_dict.get('dataset_id') or ''}",
            f"Docket ID: {inspection_dict.get('docket_id') or ''}",
            f"Case Name: {inspection_dict.get('case_name') or ''}",
            f"Court: {inspection_dict.get('court') or ''}",
            f"Document Count: {inspection_dict.get('document_count') or 0}",
            f"Attachment Count: {inspection_dict.get('attachment_count') or 0}",
            f"Latest Proof Packet ID: {inspection_dict.get('latest_proof_packet_id') or ''}",
            f"Latest Proof Packet Version: {inspection_dict.get('latest_proof_packet_version') or 0}",
            f"Latest Routing Reason: {inspection_dict.get('latest_routing_reason') or ''}",
            f"Preferred Corpus Priority: {', '.join(str(item) for item in preferred_corpus_priority)}",
            f"Preferred State Codes: {', '.join(str(item) for item in preferred_state_codes)}",
            f"Routing Evidence Count: {inspection_dict.get('routing_evidence_count') or 0}",
            f"Top Routing Citation: {inspection_dict.get('top_routing_citation') or ''}",
            f"Top Routing Source URL: {inspection_dict.get('top_routing_source_url') or ''}",
            f"Authority Backed: {bool(routing_provenance.get('authority_backed'))}",
        ]
        if top_routing:
            lines.extend(
                [
                    f"Top Routing Source Title: {top_routing.get('source_title') or ''}",
                    f"Top Routing Source CID: {top_routing.get('source_cid') or ''}",
                    f"Top Routing Source Ref: {top_routing.get('source_ref') or ''}",
                ]
            )

        if normalized_format == "text":
            return "\n".join(lines) + "\n"

        markdown_lines = [
            "# Packaged Docket Provenance Report",
            "",
            f"- Dataset ID: {inspection_dict.get('dataset_id') or ''}",
            f"- Docket ID: {inspection_dict.get('docket_id') or ''}",
            f"- Case Name: {inspection_dict.get('case_name') or ''}",
            f"- Court: {inspection_dict.get('court') or ''}",
            f"- Document Count: {inspection_dict.get('document_count') or 0}",
            f"- Attachment Count: {inspection_dict.get('attachment_count') or 0}",
            f"- Latest Proof Packet ID: {inspection_dict.get('latest_proof_packet_id') or ''}",
            f"- Latest Proof Packet Version: {inspection_dict.get('latest_proof_packet_version') or 0}",
            f"- Latest Routing Reason: {inspection_dict.get('latest_routing_reason') or ''}",
            f"- Preferred Corpus Priority: {', '.join(str(item) for item in preferred_corpus_priority)}",
            f"- Preferred State Codes: {', '.join(str(item) for item in preferred_state_codes)}",
            f"- Routing Evidence Count: {inspection_dict.get('routing_evidence_count') or 0}",
            f"- Top Routing Citation: {inspection_dict.get('top_routing_citation') or ''}",
            f"- Top Routing Source URL: {inspection_dict.get('top_routing_source_url') or ''}",
            f"- Authority Backed: {bool(routing_provenance.get('authority_backed'))}",
        ]
        if top_routing:
            markdown_lines.extend(
                [
                    f"- Top Routing Source Title: {top_routing.get('source_title') or ''}",
                    f"- Top Routing Source CID: {top_routing.get('source_cid') or ''}",
                    f"- Top Routing Source Ref: {top_routing.get('source_ref') or ''}",
                ]
            )
        return "\n".join(markdown_lines) + "\n"

    def render_packaged_inspection_report(
        self,
        manifest_path: str | Path,
        *,
        report_format: str = "markdown",
    ) -> str:
        inspection = self.inspect_packaged_bundle(manifest_path)
        return self.render_packaged_inspection_report_from_inspection(
            inspection,
            report_format=report_format,
        )

    def _rebuild_dataset(
        self,
        manifest: Dict[str, Any],
        rows_by_piece: Mapping[str, Sequence[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        dataset_core = dict((rows_by_piece.get("dataset_core") or [{}])[0])
        deontic_nodes = {
            str(row.get("node_id") or ""): self._parse_possible_json(row.get("payload_json"))
            for row in list(rows_by_piece.get("deontic_nodes") or [])
            if str(row.get("node_id") or "")
        }
        deontic_rules = {
            str(row.get("rule_id") or ""): self._parse_possible_json(row.get("payload_json"))
            for row in list(rows_by_piece.get("deontic_rules") or [])
            if str(row.get("rule_id") or "")
        }
        package_manifest = dict(manifest)
        package_manifest["attachments"] = self._restore_rows(rows_by_piece.get("attachments"))
        bm25_documents = self._restore_rows(rows_by_piece.get("bm25_documents"))
        vector_items = self._restore_rows(rows_by_piece.get("vector_items"))
        proof_agenda = self._restore_rows(rows_by_piece.get("proof_agenda"))
        proof_plans = self._restore_rows(rows_by_piece.get("proof_tactician_plans"))
        proof_evidence_packets = self._restore_rows(rows_by_piece.get("proof_evidence_packets"))
        proof_store_entries = {
            str(row.get("proof_id") or ""): self._parse_possible_json(row.get("payload_json"))
            for row in list(rows_by_piece.get("proof_store_entries") or [])
            if str(row.get("proof_id") or "")
        }
        proof_store_certificates = self._restore_rows(rows_by_piece.get("proof_store_certificates"))
        temporal_formula_rows = self._restore_rows(rows_by_piece.get("temporal_formulas"))
        dcec_formula_rows = self._restore_rows(rows_by_piece.get("dcec_formulas"))
        frame_logic_rows = self._restore_rows(rows_by_piece.get("frame_logic_frames"))
        proof_knowledge_graph_entities = self._restore_rows(rows_by_piece.get("proof_knowledge_graph_entities"))
        proof_knowledge_graph_relationships = self._restore_rows(rows_by_piece.get("proof_knowledge_graph_relationships"))
        proof_assistant_meta_row = dict((rows_by_piece.get("proof_assistant_metadata") or [{}])[0])
        proof_assistant_metadata = self._parse_possible_json(proof_assistant_meta_row.get("metadata_json")) or {}
        proof_assistant_summary = self._parse_possible_json(proof_assistant_meta_row.get("summary_json")) or {}
        metadata = json.loads(str(dataset_core.get("metadata_json") or "{}"))
        artifact_provenance = dict((metadata or {}).get("artifact_provenance") or {})
        current_packet_count = sum(1 for item in proof_evidence_packets if bool(item.get("is_current", True)))
        superseded_packet_count = sum(1 for item in proof_evidence_packets if bool(item.get("superseded")))
        sorted_proof_agenda = _sort_proof_agenda_items(proof_agenda)
        revalidation_counts = _count_agenda_revalidation_items(sorted_proof_agenda)
        return {
            "dataset_id": str(dataset_core.get("dataset_id") or manifest.get("dataset_id") or ""),
            "docket_id": str(dataset_core.get("docket_id") or manifest.get("docket_id") or ""),
            "case_name": str(dataset_core.get("case_name") or manifest.get("case_name") or ""),
            "court": str(dataset_core.get("court") or manifest.get("court") or ""),
            "documents": self._restore_rows(rows_by_piece.get("documents")),
            "plaintiff_docket": self._restore_rows(rows_by_piece.get("plaintiff_docket")),
            "defendant_docket": self._restore_rows(rows_by_piece.get("defendant_docket")),
            "authorities": self._restore_rows(rows_by_piece.get("authorities")),
            "knowledge_graph": {
                "entities": self._restore_rows(rows_by_piece.get("knowledge_graph_entities")),
                "relationships": self._restore_rows(rows_by_piece.get("knowledge_graph_relationships")),
            },
            "deontic_graph": {
                "nodes": deontic_nodes,
                "rules": deontic_rules,
            },
            "deontic_triggers": {
                "entries": self._restore_rows(rows_by_piece.get("deontic_trigger_entries")),
            },
            "bm25_index": {
                "backend": str((artifact_provenance.get("bm25_index") or {}).get("backend") or "local_bm25"),
                "documents": bm25_documents,
                "document_count": len(bm25_documents),
            },
            "vector_index": {
                "backend": str((artifact_provenance.get("vector_index") or {}).get("backend") or "local_hashed_term_projection"),
                "items": vector_items,
                "document_count": len(vector_items),
            },
            "proof_assistant": {
                "agenda": sorted_proof_agenda,
                "summary": {
                    "work_item_count": len(sorted_proof_agenda),
                    "tactician_plan_count": len(proof_plans),
                    "proof_packet_count": len(proof_evidence_packets),
                    "current_proof_packet_count": current_packet_count,
                    "superseded_proof_packet_count": superseded_packet_count,
                    "proof_count": len(proof_store_entries),
                    "temporal_formula_count": len(temporal_formula_rows),
                    "dcec_formula_count": len(dcec_formula_rows),
                    "frame_count": len(frame_logic_rows),
                    **revalidation_counts,
                    **dict(proof_assistant_summary),
                },
                "tactician": {
                    "plans": proof_plans,
                    "summary": {
                        "plan_count": len(proof_plans),
                        "local_first": True,
                    },
                },
                "temporal_fol": {
                    "formulas": [str(row.get("formula") or "") for row in temporal_formula_rows if str(row.get("formula") or "").strip()],
                },
                "deontic_temporal_first_order_logic": {
                    "formulas": [str(row.get("formula") or "") for row in temporal_formula_rows if str(row.get("formula") or "").strip()],
                },
                "deontic_cognitive_event_calculus": {
                    "formulas": [str(row.get("formula") or "") for row in dcec_formula_rows if str(row.get("formula") or "").strip()],
                },
                "frames": {
                    str(row.get("frame_id") or row.get("id") or f"frame_{index}"): dict(row)
                    for index, row in enumerate(frame_logic_rows, start=1)
                    if isinstance(row, dict)
                },
                "frame_logic": {
                    str(row.get("frame_id") or row.get("id") or f"frame_{index}"): dict(row)
                    for index, row in enumerate(frame_logic_rows, start=1)
                    if isinstance(row, dict)
                },
                "knowledge_graph": {
                    "entities": proof_knowledge_graph_entities,
                    "relationships": proof_knowledge_graph_relationships,
                },
                "evidence_packets": proof_evidence_packets,
                "proof_store": {
                    "proofs": proof_store_entries,
                    "certificates": proof_store_certificates,
                    "summary": {
                        "proof_count": len(proof_store_entries),
                        "packet_count": len(proof_evidence_packets),
                        "current_packet_count": current_packet_count,
                        "superseded_packet_count": superseded_packet_count,
                        "certificate_count": len(proof_store_certificates),
                    },
                    "metadata": {
                        "backend": "packaged_docket_proof_store",
                        "zkp_status": "not_implemented",
                    },
                },
                "metadata": dict(proof_assistant_metadata),
            },
            "metadata": metadata,
            "package_manifest": package_manifest,
        }

    def _parse_possible_json(self, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except Exception:
                    return value
        return value

    def _restore_rows(self, rows: Sequence[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
        restored: List[Dict[str, Any]] = []
        for row in list(rows or []):
            restored.append({str(key): self._parse_possible_json(value) for key, value in dict(row).items()})
        return restored

    def _resolve_manifest(
        self,
        manifest_path: str | Path,
        *,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> tuple[Path, Dict[str, Any]]:
        path = Path(manifest_path)
        if path.is_dir():
            bundle_dir = path
            manifest_file = bundle_dir / "bundle_manifest.json"
            if not manifest_file.exists():
                manifest_file = bundle_dir / "manifest.json"
            resolved_manifest = dict(manifest) if manifest is not None else json.loads(manifest_file.read_text(encoding="utf-8"))
            return bundle_dir, resolved_manifest
        suffix = path.suffix.lower()
        if suffix == ".zip":
            bundle_dir, resolved_manifest = self._resolve_zipped_manifest(path, manifest=manifest)
            return bundle_dir, resolved_manifest
        if suffix == ".parquet":
            bundle_dir = self._bundle_dir_from_manifest_sidecar(path)
            resolved_manifest = dict(manifest) if manifest is not None else self._load_manifest_from_parquet(path)
            return bundle_dir, resolved_manifest
        if suffix == ".car":
            bundle_dir = self._bundle_dir_from_manifest_sidecar(path)
            manifest_parquet = self._materialize_manifest_parquet_from_car(path)
            resolved_manifest = dict(manifest) if manifest is not None else self._load_manifest_from_parquet(manifest_parquet)
            return bundle_dir, resolved_manifest
        else:
            manifest_file = path
            bundle_dir = manifest_file.parent
        resolved_manifest = dict(manifest) if manifest is not None else json.loads(manifest_file.read_text(encoding="utf-8"))
        return bundle_dir, resolved_manifest

    def _load_manifest_from_parquet(self, manifest_parquet_path: Path) -> Dict[str, Any]:
        table = pq.read_table(manifest_parquet_path)
        rows = table.to_pylist()
        if not rows:
            raise ValueError(f"Manifest parquet contained no rows: {manifest_parquet_path}")
        manifest_json = str(rows[0].get("manifest_json") or "").strip()
        if not manifest_json:
            raise ValueError(f"Manifest parquet missing manifest_json: {manifest_parquet_path}")
        return dict(json.loads(manifest_json))

    def _bundle_dir_from_manifest_sidecar(self, path: Path) -> Path:
        parent = path.parent
        if parent.name == "parquet" or parent.name == "car":
            return parent.parent
        return parent

    def _resolve_zipped_manifest(
        self,
        archive_path: Path,
        *,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> tuple[Path, Dict[str, Any]]:
        cache_key = str(archive_path.resolve())
        temp_dir_obj = self._temp_bundle_dirs.get(cache_key)
        if temp_dir_obj is None:
            safe_temp_root = os.environ.get("IPFS_DATASETS_SAFE_ROOT") or str(Path.cwd())
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="docket_bundle_zip_", dir=safe_temp_root)
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(temp_dir_obj.name)
            self._temp_bundle_dirs[cache_key] = temp_dir_obj
        extracted_root = Path(temp_dir_obj.name)
        manifest_candidates = sorted(extracted_root.rglob("bundle_manifest.json")) or sorted(extracted_root.rglob("manifest.json"))
        if not manifest_candidates:
            raise FileNotFoundError(f"No bundle manifest found in zip archive: {archive_path}")
        manifest_file = manifest_candidates[0]
        bundle_dir = manifest_file.parent
        resolved_manifest = dict(manifest) if manifest is not None else json.loads(manifest_file.read_text(encoding="utf-8"))
        return bundle_dir, resolved_manifest

    def _materialize_manifest_parquet_from_car(self, manifest_car_path: Path) -> Path:
        cache_key = f"manifest::{manifest_car_path.resolve()}"
        temp_dir_obj = self._temp_piece_dirs.get(cache_key)
        if temp_dir_obj is None:
            safe_temp_root = os.environ.get("IPFS_DATASETS_SAFE_ROOT") or str(Path.cwd())
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="docket_manifest_car_", dir=safe_temp_root)
            self._temp_piece_dirs[cache_key] = temp_dir_obj
        temp_dir = Path(temp_dir_obj.name)
        parquet_path = temp_dir / "bundle_manifest.parquet"
        if not parquet_path.exists():
            self._car_utils.car_to_parquet(str(manifest_car_path), str(parquet_path))
        return parquet_path

    def _resolve_piece_parquet_path(self, bundle_dir: Path, piece: Mapping[str, Any]) -> Path | None:
        parquet_path = bundle_dir / str(piece.get("parquet_path") or "")
        if parquet_path.exists():
            return parquet_path
        car_rel = str(piece.get("car_path") or "").strip()
        if not car_rel:
            return None
        car_path = bundle_dir / car_rel
        if not car_path.exists():
            return None
        cache_key = f"piece::{car_path.resolve()}"
        temp_dir_obj = self._temp_piece_dirs.get(cache_key)
        if temp_dir_obj is None:
            safe_temp_root = os.environ.get("IPFS_DATASETS_SAFE_ROOT") or str(Path.cwd())
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="docket_piece_car_", dir=safe_temp_root)
            self._temp_piece_dirs[cache_key] = temp_dir_obj
        temp_dir = Path(temp_dir_obj.name)
        piece_parquet_path = temp_dir / f"{str(piece.get('piece_id') or 'piece')}.parquet"
        if not piece_parquet_path.exists():
            self._car_utils.car_to_parquet(str(car_path), str(piece_parquet_path))
        return piece_parquet_path


class PackagedDocketQueryAdapter:
    """Lazy search helpers over packaged docket dataset pieces."""

    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = manifest_path
        self._packager = DocketDatasetPackager()

    def plan_query(self, query: str) -> PackagedQueryExecutionPlan:
        lowered = str(query or "").strip().lower()
        manifest = self._manifest()
        candidates: List[PackagedQueryExecutionPlan] = []
        if any(token in lowered for token in ("temporal", "formula", "formulas", "dcec", "calculus", "frame", "frames", "logic artifact", "frame logic")):
            candidates.extend(
                [
                    self._make_plan(
                        query=query,
                        strategy="logic-artifacts",
                        target="logic_artifacts",
                        piece_ids=["temporal_formulas", "dcec_formulas", "frame_logic_frames"],
                        rationale="The query explicitly targets archived logic artifacts, so temporal formulas, DCEC formulas, and frame rows are the narrowest useful packaged pieces.",
                        priority=0,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "temporal_formulas",
                                "piece_ids": ["temporal_formulas"],
                                "purpose": "Load temporal formulas first because they are the cheapest symbolic artifact rows.",
                                "continue_on_success": True,
                                "result_policy": {
                                    "merge_mode": "by_artifact",
                                    "ranking": "logic_score_desc",
                                },
                            },
                            {
                                "name": "logic_expansion",
                                "piece_ids": ["temporal_formulas", "dcec_formulas", "frame_logic_frames"],
                                "purpose": "Expand to DCEC and frame rows if temporal formulas alone are insufficient.",
                                "continue_on_success": True,
                                "result_policy": {
                                    "merge_mode": "by_artifact",
                                    "ranking": "logic_score_desc",
                                    "artifact_priority": ["temporal_formula", "dcec_formula", "frame_logic_frame"],
                                },
                            },
                        ],
                    ),
                    self._make_plan(
                        query=query,
                        strategy="logic-fallback-proof",
                        target="proof_tasks",
                        piece_ids=["proof_agenda", "proof_tactician_plans", "deontic_trigger_entries", "proof_store_entries"],
                        rationale="If explicit logic artifacts are too thin, fall back to proof-oriented packaged artifacts.",
                        priority=1,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "proof_context",
                                "piece_ids": ["proof_agenda", "proof_tactician_plans", "deontic_trigger_entries", "proof_store_entries"],
                                "purpose": "Use proof artifacts as the first fallback when symbolic logic rows do not match.",
                                "result_policy": {
                                    "merge_mode": "by_work_item",
                                    "ranking": "proof_context",
                                },
                            }
                        ],
                    ),
                ]
            )
        elif any(token in lowered for token in ("proof", "obligation", "duty", "must", "shall", "prohibition", "permission")):
            candidates.extend(
                [
                    self._make_plan(
                        query=query,
                        strategy="proof-first",
                        target="proof_tasks",
                        piece_ids=[
                            "proof_agenda",
                            "proof_tactician_plans",
                            "deontic_trigger_entries",
                            "proof_evidence_packets",
                            "proof_store_entries",
                        ],
                        rationale="The query looks deontic/proof-oriented, so proof agenda, stored proof packets, and tactician plans are the narrowest useful packaged pieces.",
                        priority=0,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "proof_agenda",
                                "piece_ids": ["proof_agenda"],
                                "purpose": "Load the smallest proof work queue first.",
                                "continue_on_success": True,
                                "result_policy": {
                                    "merge_mode": "by_work_item",
                                    "ranking": "proof_baseline",
                                },
                            },
                            {
                                "name": "proof_context",
                                "piece_ids": [
                                    "proof_agenda",
                                    "proof_tactician_plans",
                                    "deontic_trigger_entries",
                                    "proof_evidence_packets",
                                    "proof_store_entries",
                                ],
                                "purpose": "Expand to tactician plans, stored proof packets, and trigger context if the agenda alone is insufficient.",
                                "continue_on_success": True,
                                "result_policy": {
                                    "merge_mode": "by_work_item",
                                    "ranking": "proof_context",
                                    "prefer_authority_sources": True,
                                    "prefer_plans": True,
                                    "prefer_source_types": ["proof_packet", "authority", "party_analysis", "docket_item"],
                                },
                            },
                        ],
                    ),
                    self._make_plan(
                        query=query,
                        strategy="proof-fallback-bm25",
                        target="bm25_search",
                        piece_ids=["bm25_documents", "documents"],
                        rationale="If proof artifacts are thin, the cheapest fallback is lexical search over packaged document rows.",
                        priority=1,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "bm25_index",
                                "piece_ids": ["bm25_documents"],
                                "purpose": "Try lexical ranking before loading full document rows.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            },
                            {
                                "name": "document_rows",
                                "piece_ids": ["bm25_documents", "documents"],
                                "purpose": "Load document rows if the sparse index does not produce enough hits.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            },
                        ],
                    ),
                ]
            )
        elif any(token in lowered for token in ("graph", "relationship", "entity", "authority network", "knowledge graph")):
            candidates.extend(
                [
                    self._make_plan(
                        query=query,
                        strategy="knowledge-graph",
                        target="knowledge_graph",
                        piece_ids=["knowledge_graph_entities", "knowledge_graph_relationships"],
                        rationale="The query asks for graph structure, so only packaged KG entities and relationships should be loaded.",
                        priority=0,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "kg_entities",
                                "piece_ids": ["knowledge_graph_entities"],
                                "purpose": "Load entities first for a cheap graph overview.",
                                "continue_on_success": True,
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["knowledge_graph_entities"],
                                },
                            },
                            {
                                "name": "kg_relationships",
                                "piece_ids": ["knowledge_graph_entities", "knowledge_graph_relationships"],
                                "purpose": "Expand to relationships when entity-only context is not enough.",
                                "continue_on_success": True,
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["knowledge_graph_entities", "knowledge_graph_relationships"],
                                },
                            },
                        ],
                    ),
                    self._make_plan(
                        query=query,
                        strategy="graph-minimal-metadata",
                        target="metadata",
                        piece_ids=["dataset_core"],
                        rationale="A minimal metadata read is the cheapest fallback if graph pieces are empty.",
                        priority=1,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "dataset_core",
                                "piece_ids": ["dataset_core"],
                                "purpose": "Return the cheapest package-level context when graph artifacts are unavailable.",
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["dataset_core"],
                                },
                            }
                        ],
                    ),
                ]
            )
        elif any(token in lowered for token in ("similar", "semantic", "concept", "like", "related")):
            candidates.extend(
                [
                    self._make_plan(
                        query=query,
                        strategy="semantic-vector",
                        target="vector_search",
                        piece_ids=["vector_items"],
                        rationale="The query looks semantic rather than lexical, so packaged vector items are the best first load.",
                        priority=0,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "vector_items",
                                "piece_ids": ["vector_items"],
                                "purpose": "Semantic search can operate directly on vector rows.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            }
                        ],
                    ),
                    self._make_plan(
                        query=query,
                        strategy="semantic-fallback-bm25",
                        target="bm25_search",
                        piece_ids=["bm25_documents", "documents"],
                        rationale="If vector rows are unavailable, lexical search is the next-cheapest valid route.",
                        priority=1,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "bm25_index",
                                "piece_ids": ["bm25_documents"],
                                "purpose": "Try lexical ranking before loading full document rows.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            },
                            {
                                "name": "document_rows",
                                "piece_ids": ["bm25_documents", "documents"],
                                "purpose": "Expand to document rows if the sparse index is too thin.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            },
                        ],
                    ),
                ]
            )
        elif any(token in lowered for token in ("document", "filing", "complaint", "answer", "motion", "order", "notice", "search", "find")):
            candidates.extend(
                [
                    self._make_plan(
                        query=query,
                        strategy="lexical-bm25",
                        target="bm25_search",
                        piece_ids=["bm25_documents", "documents"],
                        rationale="The query is document-centric, so packaged BM25 rows and document records are sufficient for a lexical-first search.",
                        priority=0,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "bm25_index",
                                "piece_ids": ["bm25_documents"],
                                "purpose": "Start with the sparse lexical index for the cheapest first pass.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            },
                            {
                                "name": "document_rows",
                                "piece_ids": ["bm25_documents", "documents"],
                                "purpose": "Load document rows only if the first lexical pass is too sparse.",
                                "result_policy": {
                                    "merge_mode": "by_document",
                                    "ranking": "score_desc",
                                },
                            },
                        ],
                    ),
                    self._make_plan(
                        query=query,
                        strategy="document-minimal",
                        target="metadata",
                        piece_ids=["documents"],
                        rationale="A direct document piece load is the cheapest fallback when BM25 rows are unavailable.",
                        priority=1,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "documents",
                                "piece_ids": ["documents"],
                                "purpose": "Read raw document rows when the sparse index is absent.",
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["documents"],
                                },
                            }
                        ],
                    ),
                ]
            )
        else:
            candidates.extend(
                [
                    self._make_plan(
                        query=query,
                        strategy="minimal-manifest",
                        target="metadata",
                        piece_ids=["dataset_core", "documents"],
                        rationale="The query is broad or ambiguous, so start with minimal package metadata and documents.",
                        priority=0,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "dataset_core",
                                "piece_ids": ["dataset_core"],
                                "purpose": "Load only core package metadata for the first pass.",
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["dataset_core", "documents"],
                                },
                            },
                            {
                                "name": "documents",
                                "piece_ids": ["dataset_core", "documents"],
                                "purpose": "Expand to document rows only if core metadata is not enough.",
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["dataset_core", "documents"],
                                },
                            },
                        ],
                    ),
                    self._make_plan(
                        query=query,
                        strategy="minimal-core-only",
                        target="metadata",
                        piece_ids=["dataset_core"],
                        rationale="If the caller only needs a cheap first pass, the dataset core is the lowest-cost manifest read.",
                        priority=1,
                        manifest=manifest,
                        stages=[
                            {
                                "name": "dataset_core",
                                "piece_ids": ["dataset_core"],
                                "purpose": "Return the lowest-cost package view.",
                                "result_policy": {
                                    "merge_mode": "by_piece",
                                    "piece_priority": ["dataset_core"],
                                },
                            }
                        ],
                    ),
                ]
            )
        return min(candidates, key=lambda plan: (plan.priority, plan.estimated_cost, len(plan.piece_ids), plan.strategy))

    def execute_plan(self, plan: PackagedQueryExecutionPlan | Dict[str, Any], *, top_k: int = 10) -> Dict[str, Any]:
        resolved_plan = plan if isinstance(plan, PackagedQueryExecutionPlan) else PackagedQueryExecutionPlan(
            query=str(plan.get("query") or ""),
            strategy=str(plan.get("strategy") or ""),
            target=str(plan.get("target") or ""),
            piece_ids=[str(value) for value in list(plan.get("piece_ids") or [])],
            rationale=str(plan.get("rationale") or ""),
            priority=int(plan.get("priority") or 0),
            estimated_cost=int(plan.get("estimated_cost") or 0),
            piece_costs=dict(plan.get("piece_costs") or {}),
            stages=[dict(stage) for stage in list(plan.get("stages") or [])],
        )
        execution_stages: List[Dict[str, Any]] = []
        active_result: Dict[str, Any] = {}
        for stage_index, stage in enumerate(list(resolved_plan.stages or []), start=1):
            stage_piece_ids = [str(piece_id) for piece_id in list(stage.get("piece_ids") or []) if str(piece_id).strip()]
            stage_result = self._execute_target(
                resolved_plan.target,
                resolved_plan.query,
                stage_piece_ids or resolved_plan.piece_ids,
                top_k=top_k,
            )
            stage_policy = dict(stage.get("result_policy") or {})
            stage_result = self._apply_stage_policy(
                resolved_plan.target,
                stage_result,
                stage_policy,
                top_k=top_k,
            )
            active_result = self._merge_stage_result(
                resolved_plan.target,
                active_result,
                stage_result,
                stage_policy=stage_policy,
                top_k=top_k,
            )
            execution_stages.append(
                {
                    "stage_index": stage_index,
                    "stage_name": str(stage.get("name") or f"stage_{stage_index}"),
                    "piece_ids": stage_piece_ids,
                    "estimated_cost": int(stage.get("estimated_cost") or 0),
                    "result_count": int(stage_result.get("result_count") or 0),
                    "cumulative_result_count": int(active_result.get("result_count") or 0),
                    "source": str(stage_result.get("source") or ""),
                    "result_policy": _jsonable(stage_policy),
                }
            )
            if self._stage_satisfied(resolved_plan.target, stage_result, top_k=top_k) and not bool(stage.get("continue_on_success")):
                break

        if not execution_stages:
            active_result = self._execute_target(
                resolved_plan.target,
                resolved_plan.query,
                resolved_plan.piece_ids,
                top_k=top_k,
            )
        result = dict(active_result)
        result["execution_plan"] = resolved_plan.to_dict()
        result["execution_stages"] = execution_stages
        result["stages_executed"] = len(execution_stages) or 1
        result["escalation"] = self._build_escalation_guidance(
            resolved_plan,
            result,
            execution_stages=execution_stages,
            top_k=top_k,
        )
        return result

    def search_bm25(
        self,
        query: str,
        *,
        top_k: int = 10,
        piece_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        requested = {str(piece_id) for piece_id in list(piece_ids or ["bm25_documents"]) if str(piece_id).strip()}
        rows = self._packager.load_package_piece(self.manifest_path, "bm25_documents") if "bm25_documents" in requested else []
        documents = self._packager.load_package_piece(self.manifest_path, "documents") if "documents" in requested else []
        results: List[Dict[str, Any]] = []
        if rows:
            normalized_rows = []
            for row in rows:
                metadata = self._parse_possible_json(row.get("metadata"))
                normalized_rows.append(
                    {
                        "id": row.get("id"),
                        "text": row.get("text"),
                        "title": (metadata or {}).get("title"),
                        "metadata": dict(metadata or {}),
                    }
                )
            results = bm25_search_documents(query, normalized_rows, top_k=top_k)
        if not results and documents:
            results = bm25_search_documents(query, documents, top_k=top_k)
        return {
            "query": query,
            "top_k": top_k,
            "results": results,
            "result_count": len(results),
            "source": "packaged_local_bm25",
        }

    def search_vector(
        self,
        query: str,
        *,
        top_k: int = 10,
        piece_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        requested = {str(piece_id) for piece_id in list(piece_ids or ["vector_items"]) if str(piece_id).strip()}
        rows = self._packager.load_package_piece(self.manifest_path, "vector_items") if "vector_items" in requested else []
        vector_meta = self._vector_backend_metadata()
        query_vector = embed_query_for_backend(
            query,
            backend=str(vector_meta.get("backend") or "local_hashed_term_projection"),
            dimension=self._infer_vector_dimension(rows),
            provider=str(vector_meta.get("provider") or "") or None,
            model_name=str(vector_meta.get("model_name") or "") or None,
        )
        scored: List[Dict[str, Any]] = []
        for row in rows:
            parsed_vector = self._parse_possible_json(row.get("vector"))
            vector = [float(value) for value in list(parsed_vector or [])]
            score = vector_dot(query_vector, vector)
            scored.append(
                {
                    "document_id": row.get("document_id"),
                    "title": row.get("title"),
                    "date_filed": row.get("date_filed"),
                    "document_number": row.get("document_number"),
                    "score": score,
                    "backend": "local_hashed_term_projection",
                }
            )
        scored.sort(
            key=lambda item: (
                float(item.get("score") or 0.0),
                1 if bool(item.get("is_current")) else 0,
                int(item.get("packet_version") or 0),
            ),
            reverse=True,
        )
        results = scored[:top_k]
        return {
            "query": query,
            "top_k": top_k,
            "results": results,
            "result_count": len(results),
            "source": "packaged_vector_items",
        }

    def search_proof_tasks(
        self,
        query: str,
        *,
        top_k: int = 10,
        piece_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        requested = {
            str(piece_id)
            for piece_id in list(
                piece_ids or ["proof_agenda", "proof_tactician_plans", "proof_evidence_packets", "proof_store_entries"]
            )
            if str(piece_id).strip()
        }
        agenda = self._packager.load_package_piece(self.manifest_path, "proof_agenda") if "proof_agenda" in requested else []
        plans = self._packager.load_package_piece(self.manifest_path, "proof_tactician_plans") if "proof_tactician_plans" in requested else []
        triggers = self._packager.load_package_piece(self.manifest_path, "deontic_trigger_entries") if "deontic_trigger_entries" in requested else []
        proof_packets = self._packager.load_package_piece(self.manifest_path, "proof_evidence_packets") if "proof_evidence_packets" in requested else []
        proof_store_rows = self._packager.load_package_piece(self.manifest_path, "proof_store_entries") if "proof_store_entries" in requested else []
        query_terms = {term for term in str(query or "").lower().split() if term}
        scored: List[Dict[str, Any]] = []
        plan_map = {str(item.get("work_item_id") or ""): dict(item) for item in plans}
        trigger_map = {str(item.get("trigger_id") or ""): dict(item) for item in triggers}
        for item in agenda:
            combined = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("action") or ""),
                    str(item.get("party") or ""),
                    str(item.get("modality") or ""),
                ]
            ).lower()
            overlap = sum(1 for term in query_terms if term in combined)
            if overlap <= 0:
                continue
            work_item_id = str(item.get("work_item_id") or "")
            trigger = trigger_map.get(str(item.get("trigger_id") or ""), {})
            authority_backed = bool(
                str(item.get("source_type") or "") == "authority"
                or str(trigger.get("source_type") or "") == "authority"
                or int(trigger.get("authority_count") or 0) > 0
            )
            scored.append(
                {
                    "work_item_id": work_item_id,
                    "title": item.get("title"),
                    "party": item.get("party"),
                    "action": item.get("action"),
                    "modality": item.get("modality"),
                    "score": (
                        overlap / max(1, len(query_terms))
                    ) + (
                        0.2 * _proof_revalidation_priority_rank(str(item.get("proof_revalidation_priority") or ""))
                    ),
                    "plan": plan_map.get(work_item_id, {}),
                    "source_type": item.get("source_type"),
                    "authority_ids": list(item.get("authority_ids") or []),
                    "authority_backed": authority_backed,
                    "authority_count": int(trigger.get("authority_count") or 0),
                    "trigger": trigger,
                    "current_proof_packet_review_required": bool(item.get("current_proof_packet_review_required")),
                    "current_proof_packet_review_trigger": (
                        self._parse_possible_json(item.get("current_proof_packet_review_trigger"))
                        if not isinstance(item.get("current_proof_packet_review_trigger"), Mapping)
                        else dict(item.get("current_proof_packet_review_trigger") or {})
                    ) or {},
                    "proof_revalidation_status": str(item.get("proof_revalidation_status") or ""),
                    "proof_revalidation_priority": str(item.get("proof_revalidation_priority") or ""),
                    "selection_rationale": (
                        "Work item matches the proof query and is flagged for proof revalidation."
                        if bool(item.get("current_proof_packet_review_required"))
                        else "Work item matches the proof query and has stable packaged support."
                    ),
                }
            )
        packet_map = {
            str(item.get("proof_id") or ""): dict(item)
            for item in proof_packets
            if str(item.get("proof_id") or "")
        }
        for row in proof_store_rows:
            proof_id = str(row.get("proof_id") or "")
            proof_payload = self._parse_possible_json(row.get("payload_json"))
            if not proof_id or not isinstance(proof_payload, Mapping):
                continue
            evidence_bundle = dict(proof_payload.get("evidence_bundle") or {})
            combined = " ".join(
                [
                    str(proof_payload.get("query") or ""),
                    str(proof_payload.get("title") or ""),
                    str(proof_payload.get("action") or ""),
                    str(proof_payload.get("party") or ""),
                    " ".join(str(item.get("title") or "") for item in list(evidence_bundle.get("evidence_items") or [])),
                    " ".join(str(item.get("excerpt") or "") for item in list(evidence_bundle.get("evidence_items") or [])),
                ]
            ).lower()
            overlap = sum(1 for term in query_terms if term in combined)
            if overlap <= 0:
                continue
            supporting_sources = list(
                dict.fromkeys(
                    str(item.get("best_support_source") or "")
                    for item in list(evidence_bundle.get("evidence_items") or [])
                    if str(item.get("best_support_source") or "")
                )
            )
            matched_plan = dict(proof_payload.get("matched_plan") or {})
            is_current = bool(
                proof_payload.get("is_current", packet_map.get(proof_id, {}).get("is_current", True))
            )
            support_strength = str(
                proof_payload.get("support_strength")
                or packet_map.get(proof_id, {}).get("support_strength")
                or ""
            )
            history_summary = _proof_packet_history_summary(proof_payload)
            history_rank = _proof_packet_history_rank(proof_payload)
            preference_summary = _build_proof_packet_preference_summary(
                {
                    "proof_id": proof_id,
                    "is_current": is_current,
                    "support_strength": support_strength,
                    "packet_version": int(
                        proof_payload.get("packet_version")
                        or packet_map.get(proof_id, {}).get("packet_version")
                        or 0
                    ),
                    "action_candidate_history": proof_payload.get("action_candidate_history"),
                    "metadata": proof_payload.get("metadata"),
                }
            )
            scored.append(
                {
                    "work_item_id": str(proof_payload.get("work_item_id") or ""),
                    "proof_id": proof_id,
                    "title": proof_payload.get("title") or packet_map.get(proof_id, {}).get("query") or proof_id,
                    "party": proof_payload.get("party"),
                    "action": proof_payload.get("action"),
                    "modality": proof_payload.get("modality"),
                    "score": max(
                        overlap / max(1, len(query_terms)),
                        0.5 + (0.05 * int(dict(evidence_bundle.get("summary") or {}).get("evidence_item_count") or 0)),
                    ) + (0.15 if is_current else 0.0) + (0.01 * history_rank),
                    "plan": matched_plan,
                    "source_type": "proof_packet",
                    "packet_version": int(
                        proof_payload.get("packet_version")
                        or packet_map.get(proof_id, {}).get("packet_version")
                        or 0
                    ),
                    "support_strength": support_strength,
                    "history_quality": history_rank,
                    "action_candidate_history_summary": history_summary,
                    "packet_preference_summary": preference_summary,
                    "preference_history": list(proof_payload.get("preference_history") or []),
                    "is_current": is_current,
                    "superseded": bool(
                        proof_payload.get("superseded", packet_map.get(proof_id, {}).get("superseded", False))
                    ),
                    "authority_ids": list(proof_payload.get("authority_ids") or []),
                    "authority_backed": "authority_list" in supporting_sources or bool(proof_payload.get("authority_ids")),
                    "authority_count": len(list(proof_payload.get("authority_ids") or [])),
                    "trigger": {
                        "proof_id": proof_id,
                        "supporting_sources": supporting_sources,
                        "packet_query": packet_map.get(proof_id, {}).get("query"),
                    },
                    "evidence_bundle": evidence_bundle,
                    "proof_status": proof_payload.get("status"),
                    "selection_rationale": _build_proof_packet_selection_rationale(
                        is_current=is_current,
                        support_strength=support_strength,
                        packet_version=int(
                            proof_payload.get("packet_version")
                            or packet_map.get(proof_id, {}).get("packet_version")
                            or 0
                        ),
                        action_candidate_history_summary=history_summary,
                    ),
                }
            )
        scored.sort(
            key=lambda item: (
                _proof_revalidation_priority_rank(str(item.get("proof_revalidation_priority") or "")),
                float(item.get("score") or 0.0),
                int(item.get("history_quality") or 0),
                _support_strength_rank(str(item.get("support_strength") or "")),
                1 if bool(item.get("is_current")) else 0,
                int(item.get("packet_version") or 0),
            ),
            reverse=True,
        )
        results = scored[:top_k]
        return {
            "query": query,
            "top_k": top_k,
            "results": results,
            "result_count": len(results),
            "source": "packaged_proof_agenda",
        }


    def search_logic_artifacts(
        self,
        query: str,
        *,
        top_k: int = 10,
        piece_ids: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        requested = {
            str(piece_id)
            for piece_id in list(piece_ids or ["temporal_formulas", "dcec_formulas", "frame_logic_frames"])
            if str(piece_id).strip()
        }
        temporal_rows = self._packager.load_package_piece(self.manifest_path, "temporal_formulas") if "temporal_formulas" in requested else []
        dcec_rows = self._packager.load_package_piece(self.manifest_path, "dcec_formulas") if "dcec_formulas" in requested else []
        frame_rows = self._packager.load_package_piece(self.manifest_path, "frame_logic_frames") if "frame_logic_frames" in requested else []
        query_terms = {term for term in str(query or "").lower().split() if term}
        scored: List[Dict[str, Any]] = []

        for row in temporal_rows:
            formula = str(row.get("formula") or "").strip()
            if not formula:
                continue
            overlap = sum(1 for term in query_terms if term in formula.lower())
            if overlap <= 0:
                continue
            scored.append(
                {
                    "artifact_id": str(row.get("formula_id") or ""),
                    "artifact_type": "temporal_formula",
                    "title": formula,
                    "formula": formula,
                    "piece_id": "temporal_formulas",
                    "score": overlap / max(1, len(query_terms)),
                }
            )

        for row in dcec_rows:
            formula = str(row.get("formula") or "").strip()
            if not formula:
                continue
            overlap = sum(1 for term in query_terms if term in formula.lower())
            if overlap <= 0:
                continue
            scored.append(
                {
                    "artifact_id": str(row.get("formula_id") or ""),
                    "artifact_type": "dcec_formula",
                    "title": formula,
                    "formula": formula,
                    "piece_id": "dcec_formulas",
                    "score": overlap / max(1, len(query_terms)),
                }
            )

        for index, row in enumerate(frame_rows, start=1):
            frame_id = str(row.get("frame_id") or row.get("id") or f"frame_{index}")
            label = str(row.get("label") or frame_id)
            slots = self._parse_possible_json(row.get("slots"))
            combined = " ".join(
                [
                    frame_id,
                    label,
                    json.dumps(slots, sort_keys=True) if isinstance(slots, (dict, list)) else str(slots or ""),
                    str(row.get("ergo") or ""),
                ]
            ).lower()
            overlap = sum(1 for term in query_terms if term in combined)
            if overlap <= 0:
                continue
            scored.append(
                {
                    "artifact_id": frame_id,
                    "artifact_type": "frame_logic_frame",
                    "title": label,
                    "frame": dict(row),
                    "piece_id": "frame_logic_frames",
                    "score": overlap / max(1, len(query_terms)),
                }
            )

        scored.sort(
            key=lambda item: (float(item.get("score") or 0.0), item.get("artifact_type") == "temporal_formula"),
            reverse=True,
        )
        results = scored[:top_k]
        return {
            "query": query,
            "top_k": top_k,
            "results": results,
            "result_count": len(results),
            "source": "packaged_logic_artifacts",
        }

    def _infer_vector_dimension(self, rows: Sequence[Dict[str, Any]]) -> int:
        for row in rows:
            vector = list(self._parse_possible_json(row.get("vector")) or [])
            if vector:
                return len(vector)
        return 32

    def _embed_text(self, text: str, *, dimension: int) -> List[float]:
        return hashed_term_projection(text, dimension=dimension)

    def _parse_possible_json(self, value: Any) -> Any:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("{") or text.startswith("["):
                try:
                    return json.loads(text)
                except Exception:
                    return value
        return value

    def _manifest(self) -> Dict[str, Any]:
        _, manifest = self._packager._resolve_manifest(self.manifest_path)
        return manifest

    def _vector_backend_metadata(self) -> Dict[str, Any]:
        dataset_core_rows = self._packager.load_package_piece(self.manifest_path, "dataset_core")
        dataset_core = dict((dataset_core_rows or [{}])[0])
        metadata = self._parse_possible_json(dataset_core.get("metadata_json")) or {}
        return dict(((metadata or {}).get("artifact_provenance") or {}).get("vector_index") or {})

    def _piece_cost_map(self, manifest: Dict[str, Any]) -> Dict[str, int]:
        costs: Dict[str, int] = {}
        for piece in list(manifest.get("pieces") or []):
            piece_id = str(piece.get("piece_id") or "")
            if not piece_id:
                continue
            row_count = int(piece.get("row_count") or 0)
            dependency_cost = len(list(piece.get("depends_on") or [])) * 10
            car_bonus = 0 if str(piece.get("car_path") or "").strip() else 25
            costs[piece_id] = max(1, row_count) + dependency_cost + car_bonus
        return costs

    def _execute_target(
        self,
        target: str,
        query: str,
        piece_ids: Sequence[str],
        *,
        top_k: int,
    ) -> Dict[str, Any]:
        if target == "proof_tasks":
            return self.search_proof_tasks(query, top_k=top_k, piece_ids=piece_ids)
        if target == "logic_artifacts":
            return self.search_logic_artifacts(query, top_k=top_k, piece_ids=piece_ids)
        if target == "vector_search":
            return self.search_vector(query, top_k=top_k, piece_ids=piece_ids)
        if target == "knowledge_graph":
            rows = self._packager.load_package_components(self.manifest_path, piece_ids=piece_ids)
            return {
                "query": query,
                "top_k": top_k,
                "results": [
                    {
                        "piece_id": piece_id,
                        "row_count": len(rows_for_piece),
                        "rows": rows_for_piece[:top_k],
                    }
                    for piece_id, rows_for_piece in rows.items()
                ],
                "result_count": len(rows),
                "source": "packaged_knowledge_graph",
            }
        if target == "metadata":
            rows = self._packager.load_package_components(self.manifest_path, piece_ids=piece_ids)
            return {
                "query": query,
                "top_k": top_k,
                "results": [{"piece_id": piece_id, "rows": rows_for_piece[:top_k]} for piece_id, rows_for_piece in rows.items()],
                "result_count": len(rows),
                "source": "packaged_metadata",
            }
        return self.search_bm25(query, top_k=top_k, piece_ids=piece_ids)

    def _stage_satisfied(self, target: str, result: Mapping[str, Any], *, top_k: int) -> bool:
        result_count = int(result.get("result_count") or 0)
        if target in {"knowledge_graph", "metadata", "bm25_search", "vector_search", "proof_tasks"}:
            return result_count > 0
        return result_count >= min(max(1, top_k), 3)

    def _merge_stage_result(
        self,
        target: str,
        current: Mapping[str, Any] | None,
        incoming: Mapping[str, Any],
        *,
        stage_policy: Optional[Mapping[str, Any]] = None,
        top_k: int,
    ) -> Dict[str, Any]:
        base = dict(current or {})
        if not base:
            return dict(incoming)

        merged = dict(incoming)
        merged_results = self._merge_results_by_target(
            target,
            list(base.get("results") or []),
            list(incoming.get("results") or []),
            stage_policy=stage_policy,
            top_k=top_k,
        )
        merged["results"] = merged_results
        merged["result_count"] = len(merged_results)

        base_source = str(base.get("source") or "")
        incoming_source = str(incoming.get("source") or "")
        merged["source"] = incoming_source if not base_source else (
            base_source if incoming_source == base_source else f"{base_source}+{incoming_source}"
        )
        return merged

    def _merge_results_by_target(
        self,
        target: str,
        current_results: Sequence[Mapping[str, Any]],
        incoming_results: Sequence[Mapping[str, Any]],
        *,
        stage_policy: Optional[Mapping[str, Any]] = None,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        merge_mode = str((stage_policy or {}).get("merge_mode") or "")
        if target in {"bm25_search", "vector_search", "proof_tasks"} or merge_mode in {"by_document", "by_work_item"}:
            key_fields = {
                "bm25_search": ("id", "document_id", "title"),
                "vector_search": ("document_id", "title"),
                "proof_tasks": ("work_item_id", "title"),
            }
            merged_index: Dict[str, Dict[str, Any]] = {}
            order: List[str] = []
            for candidate in list(current_results) + list(incoming_results):
                row = dict(candidate)
                identity = self._result_identity(row, key_fields[target])
                if identity not in merged_index:
                    merged_index[identity] = row
                    order.append(identity)
                    continue
                existing = merged_index[identity]
                existing_rank = self._result_rank_key(target, existing, stage_policy=stage_policy)
                row_rank = self._result_rank_key(target, row, stage_policy=stage_policy)
                preferred = row if row_rank >= existing_rank else existing
                fallback = existing if preferred is row else row
                merged_row = dict(fallback)
                merged_row.update(preferred)
                if float(existing.get("score") or 0.0) > float(row.get("score") or 0.0):
                    merged_row["score"] = existing.get("score")
                merged_index[identity] = merged_row
            merged_rows = [merged_index[item_id] for item_id in order]
            merged_rows.sort(
                key=lambda item: self._result_rank_key(target, item, stage_policy=stage_policy),
                reverse=True,
            )
            return merged_rows[:top_k]

        if target in {"knowledge_graph", "metadata"} or merge_mode == "by_piece":
            merged_index = {
                self._result_identity(dict(candidate), ("piece_id",)): dict(candidate)
                for candidate in current_results
            }
            for candidate in incoming_results:
                row = dict(candidate)
                identity = self._result_identity(row, ("piece_id",))
                if identity in merged_index:
                    existing = dict(merged_index[identity])
                    existing_rows = list(existing.get("rows") or [])
                    incoming_rows = list(row.get("rows") or [])
                    if incoming_rows:
                        existing["rows"] = incoming_rows[:top_k]
                    existing["row_count"] = max(int(existing.get("row_count") or 0), int(row.get("row_count") or 0))
                    merged_index[identity] = existing
                else:
                    merged_index[identity] = row
            merged_rows = list(merged_index.values())
            merged_rows.sort(
                key=lambda item: self._result_rank_key(target, item, stage_policy=stage_policy),
                reverse=True,
            )
            return merged_rows[:top_k]

        return [dict(item) for item in list(incoming_results)[:top_k]]

    def _apply_stage_policy(
        self,
        target: str,
        result: Mapping[str, Any],
        stage_policy: Mapping[str, Any] | None,
        *,
        top_k: int,
    ) -> Dict[str, Any]:
        policy = dict(stage_policy or {})
        ranked = dict(result)
        rows = [dict(item) for item in list(result.get("results") or [])]
        rows.sort(
            key=lambda item: self._result_rank_key(target, item, stage_policy=policy),
            reverse=True,
        )
        ranked["results"] = rows[:top_k]
        ranked["result_count"] = len(ranked["results"])
        return ranked

    def _result_rank_key(
        self,
        target: str,
        row: Mapping[str, Any],
        *,
        stage_policy: Mapping[str, Any] | None,
    ) -> tuple[Any, ...]:
        policy = dict(stage_policy or {})
        if target == "proof_tasks":
            source_priority = list(policy.get("prefer_source_types") or [])
            source_rank = len(source_priority)
            source_type = str(row.get("source_type") or "")
            if source_type in source_priority:
                source_rank = len(source_priority) - source_priority.index(source_type)
            return (
                1 if bool(policy.get("prefer_authority_sources")) and bool(row.get("authority_backed")) else 0,
                1 if bool(policy.get("prefer_plans")) and bool(row.get("plan")) else 0,
                int(row.get("history_quality") or 0),
                _support_strength_rank(str(row.get("support_strength") or "")),
                source_rank,
                int(row.get("authority_count") or 0),
                float(row.get("score") or 0.0),
            )
        if target in {"bm25_search", "vector_search"}:
            return (float(row.get("score") or 0.0),)
        if target in {"knowledge_graph", "metadata"}:
            piece_priority = list(policy.get("piece_priority") or [])
            piece_id = str(row.get("piece_id") or "")
            if piece_id in piece_priority:
                return (len(piece_priority) - piece_priority.index(piece_id), int(row.get("row_count") or len(list(row.get("rows") or []))))
            return (0, int(row.get("row_count") or len(list(row.get("rows") or []))))
        return (float(row.get("score") or 0.0),)

    def _result_identity(self, row: Mapping[str, Any], fields: Sequence[str]) -> str:
        for field in fields:
            value = row.get(field)
            if value not in (None, ""):
                return f"{field}:{value}"
        return json.dumps(_jsonable(dict(row)), sort_keys=True)

    def _build_escalation_guidance(
        self,
        plan: PackagedQueryExecutionPlan,
        result: Mapping[str, Any],
        *,
        execution_stages: Sequence[Mapping[str, Any]],
        top_k: int,
    ) -> Dict[str, Any]:
        if plan.target != "proof_tasks":
            return {
                "should_escalate": False,
                "reason": "Escalation guidance is currently only defined for proof-oriented packaged queries.",
                "recommended_source_types": [],
                "recommended_sources": [],
            }

        rows = [dict(item) for item in list(result.get("results") or [])]
        tactician_plans = self._packager.load_package_piece(self.manifest_path, "proof_tactician_plans")
        source_catalog = self._collect_source_catalog(tactician_plans)
        source_catalog.extend(self._collect_proof_packet_source_catalog(plan.query))
        matched_plan_ids = {
            str(row.get("plan", {}).get("plan_id") or "")
            for row in rows
            if str(row.get("plan", {}).get("plan_id") or "")
        }
        matched_sources = self._collect_source_catalog(
            [plan_row for plan_row in tactician_plans if str(plan_row.get("plan_id") or "") in matched_plan_ids]
        )

        has_results = bool(rows)
        authority_backed = any(bool(row.get("authority_backed")) for row in rows)
        planned = any(bool(row.get("plan")) for row in rows)
        enough_hits = len(rows) >= min(max(1, top_k), 2)
        if not enough_hits:
            enough_hits = any(
                str(row.get("source_type") or "") == "proof_packet"
                and int(dict(row.get("evidence_bundle") or {}).get("summary", {}).get("evidence_item_count") or 0) >= 1
                for row in rows
            )

        should_escalate = not has_results or not authority_backed or not planned or not enough_hits
        if not has_results:
            reason = "No packaged proof results matched the query, so the tactician should expand beyond the local proof agenda."
            preferred_types = ["proof_packet", "authority_list", "legal_dataset_parser", "search_engine"]
        elif not authority_backed:
            reason = "Packaged proof hits exist but lack authority-backed support, so the next step should consult authorities and parser-backed corpora."
            preferred_types = ["proof_packet", "authority_list", "legal_dataset_parser", "search_engine"]
        elif not planned:
            reason = "Packaged proof hits exist but do not yet carry tactician support plans, so retrieval should continue through local and parser routes."
            preferred_types = ["proof_packet", "local_docket_documents", "authority_list", "legal_dataset_parser"]
        elif not enough_hits:
            reason = "Packaged proof hits are too sparse for a confident answer, so retrieval should widen along the tactician route."
            preferred_types = ["proof_packet", "authority_list", "legal_dataset_parser", "search_engine"]
        else:
            reason = "Packaged proof results include authority-backed items with tactician plans, so escalation is not currently necessary."
            preferred_types = []

        recommended_sources = self._select_recommended_sources(
            matched_sources or source_catalog,
            preferred_types=preferred_types,
        )
        follow_up_plan = self._build_follow_up_plan(
            plan,
            recommended_sources=recommended_sources,
            result_rows=rows,
        )
        next_action_summary = self._build_next_action_summary(
            query=plan.query,
            should_escalate=bool(should_escalate),
            follow_up_plan=follow_up_plan,
            result_rows=rows,
        )
        packet_candidates = self._build_packet_candidates(rows)
        action_candidates = self._build_action_candidates(
            query=plan.query,
            follow_up_plan=follow_up_plan,
            packet_candidates=packet_candidates,
        )
        proof_preference_summary = _build_query_proof_preference_summary(
            query=plan.query,
            result_rows=rows,
            next_action_summary=next_action_summary,
            should_escalate=bool(should_escalate),
        )
        proof_preference_history_summary = _build_query_proof_preference_history_summary(
            query=plan.query,
            result_rows=rows,
            proof_preference_summary=proof_preference_summary,
        )
        proof_preference_review_trigger = _build_proof_preference_review_trigger(
            proof_preference_history_summary,
        )
        return {
            "should_escalate": bool(should_escalate),
            "reason": reason,
            "recommended_source_types": [item["source_type"] for item in recommended_sources],
            "recommended_sources": recommended_sources,
            "follow_up_plan": follow_up_plan,
            "next_action_summary": next_action_summary,
            "packet_candidates": packet_candidates,
            "action_candidates": action_candidates,
            "proof_preference_summary": proof_preference_summary,
            "proof_preference_history_summary": proof_preference_history_summary,
            "proof_preference_review_trigger": proof_preference_review_trigger,
            "observations": {
                "result_count": len(rows),
                "authority_backed_result_count": sum(1 for row in rows if bool(row.get("authority_backed"))),
                "planned_result_count": sum(1 for row in rows if bool(row.get("plan"))),
                "stages_executed": len(list(execution_stages or [])),
            },
        }

    def _collect_source_catalog(self, tactician_plans: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        catalog: Dict[str, Dict[str, Any]] = {}
        for plan in tactician_plans:
            raw_candidates = self._parse_possible_json(plan.get("candidate_sources"))
            for candidate in list(raw_candidates or []):
                parsed_candidate = self._parse_possible_json(candidate)
                if not isinstance(parsed_candidate, Mapping):
                    continue
                source = dict(parsed_candidate)
                source_id = str(source.get("source_id") or "")
                if not source_id:
                    continue
                existing = catalog.get(source_id)
                if existing is None or int(source.get("priority") or 999) < int(existing.get("priority") or 999):
                    catalog[source_id] = source
        return list(catalog.values())

    def _collect_proof_packet_source_catalog(self, query: str) -> List[Dict[str, Any]]:
        packets = self._packager.load_package_piece(self.manifest_path, "proof_evidence_packets")
        catalog: List[Dict[str, Any]] = []
        for packet in packets:
            proof_id = str(packet.get("proof_id") or "")
            if not proof_id:
                continue
            packet_query = str(packet.get("query") or query or "").strip()
            is_current = bool(packet.get("is_current", True))
            support_strength = str(packet.get("support_strength") or "")
            history_summary = _proof_packet_history_summary(packet)
            history_rank = _proof_packet_history_rank(packet)
            preference_summary = _build_proof_packet_preference_summary(packet)
            catalog.append(
                {
                    "source_id": proof_id,
                    "source_type": "proof_packet",
                    "label": str(packet.get("query") or packet.get("bundle_kind") or proof_id),
                    "priority": (0 if is_current else 10) - _support_strength_rank(support_strength) - history_rank,
                    "rationale": _build_proof_packet_selection_rationale(
                        is_current=is_current,
                        support_strength=support_strength,
                        packet_version=int(packet.get("packet_version") or 0),
                        action_candidate_history_summary=history_summary,
                    ),
                    "query_hints": [packet_query] if packet_query else [],
                    "metadata": {
                        "proof_id": proof_id,
                        "bundle_kind": str(packet.get("bundle_kind") or ""),
                        "packet_version": int(packet.get("packet_version") or 0),
                        "support_strength": support_strength,
                        "history_quality": history_rank,
                        "action_candidate_history_summary": history_summary,
                        "packet_preference_summary": preference_summary,
                        "is_current": is_current,
                        "superseded": bool(packet.get("superseded")),
                    },
                }
            )
        return catalog

    def _select_recommended_sources(
        self,
        source_catalog: Sequence[Mapping[str, Any]],
        *,
        preferred_types: Sequence[str],
    ) -> List[Dict[str, Any]]:
        preferred = [str(item) for item in preferred_types if str(item).strip()]
        ranked: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for source_type in preferred:
            candidates = [
                dict(source)
                for source in source_catalog
                if str(source.get("source_type") or "") == source_type
            ]
            candidates.sort(key=lambda item: int(item.get("priority") or 999))
            for candidate in candidates[:1]:
                source_id = str(candidate.get("source_id") or "")
                if source_id and source_id not in seen:
                    ranked.append(candidate)
                    seen.add(source_id)
        return ranked

    def _build_follow_up_plan(
        self,
        plan: PackagedQueryExecutionPlan,
        *,
        recommended_sources: Sequence[Mapping[str, Any]],
        result_rows: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        query_hints: List[str] = []
        for row in result_rows:
            for value in (
                row.get("title"),
                row.get("action"),
                row.get("party"),
                row.get("modality"),
            ):
                text = str(value or "").strip()
                if text and text not in query_hints:
                    query_hints.append(text)

        steps: List[Dict[str, Any]] = []
        for index, source in enumerate(recommended_sources, start=1):
            query_terms = [plan.query] + [str(item) for item in list(source.get("query_hints") or []) if str(item).strip()]
            for hint in query_hints:
                if hint not in query_terms:
                    query_terms.append(hint)
            retrieval_query = " ".join(term for term in query_terms if term).strip()
            source_type = str(source.get("source_type") or "")
            action_type = self._source_action_type(
                source_type,
                source=source,
            )
            steps.append(
                {
                    "step_index": index,
                    "source_id": str(source.get("source_id") or ""),
                    "source_type": source_type,
                    "action_type": action_type,
                    "label": str(source.get("label") or ""),
                    "priority": int(source.get("priority") or index),
                    "retrieval_query": retrieval_query,
                    "rationale": str(source.get("rationale") or ""),
                    "modules": list((source.get("metadata") or {}).get("modules") or []),
                    "preferred_corpus_keys": list((source.get("metadata") or {}).get("preferred_corpus_keys") or []),
                    "preferred_corpus_priority": list((source.get("metadata") or {}).get("preferred_corpus_priority") or []),
                    "preferred_dataset_ids": list((source.get("metadata") or {}).get("preferred_dataset_ids") or []),
                    "preferred_dataset_priority": list((source.get("metadata") or {}).get("preferred_dataset_priority") or []),
                    "preferred_state_codes": list((source.get("metadata") or {}).get("preferred_state_codes") or []),
                    "routing_evidence": list((source.get("metadata") or {}).get("routing_evidence") or []),
                    "routing_reason": str((source.get("metadata") or {}).get("routing_reason") or ""),
                    "authority_backed": bool((source.get("metadata") or {}).get("authority_backed")),
                }
            )
        return {
            "query": plan.query,
            "target": plan.target,
            "step_count": len(steps),
            "steps": steps,
        }

    def _source_action_type(
        self,
        source_type: str,
        *,
        source: Optional[Mapping[str, Any]] = None,
    ) -> str:
        normalized = str(source_type or "")
        metadata = dict((source or {}).get("metadata") or {})
        if normalized == "proof_packet" and bool(metadata.get("is_current", True)):
            return "reuse_current_packet"
        if normalized in {
            "authority_list",
            "local_docket_documents",
            "local_bm25_index",
            "local_vector_index",
            "legal_dataset_parser",
            "proof_packet",
        }:
            return "refresh_local_support"
        if normalized == "search_engine":
            return "escalate_outward"
        return normalized or "refresh_local_support"

    def _build_next_action_summary(
        self,
        *,
        query: str,
        should_escalate: bool,
        follow_up_plan: Mapping[str, Any],
        result_rows: Sequence[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        steps = [dict(step) for step in list(follow_up_plan.get("steps") or [])]
        if steps:
            next_step = steps[0]
            execution_hint = {
                "job_kind": "proof_retrieval_follow_up",
                "step_index": int(next_step.get("step_index") or 1),
                "source_id": str(next_step.get("source_id") or ""),
                "source_type": str(next_step.get("source_type") or ""),
                "action_type": str(next_step.get("action_type") or ""),
                "label": str(next_step.get("label") or ""),
                "retrieval_query": str(next_step.get("retrieval_query") or query),
                "modules": list(next_step.get("modules") or []),
                "preferred_corpus_keys": list(next_step.get("preferred_corpus_keys") or []),
                "preferred_corpus_priority": list(next_step.get("preferred_corpus_priority") or []),
                "preferred_dataset_ids": list(next_step.get("preferred_dataset_ids") or []),
                "preferred_dataset_priority": list(next_step.get("preferred_dataset_priority") or []),
                "preferred_state_codes": list(next_step.get("preferred_state_codes") or []),
                "routing_evidence": list(next_step.get("routing_evidence") or []),
                "routing_reason": str(next_step.get("routing_reason") or ""),
                "authority_backed": bool(next_step.get("authority_backed")),
                "rationale": str(next_step.get("rationale") or ""),
                "priority": int(next_step.get("priority") or 1),
            }
            return {
                "query": query,
                "action_type": str(next_step.get("action_type") or ""),
                "source_type": str(next_step.get("source_type") or ""),
                "source_id": str(next_step.get("source_id") or ""),
                "step_index": int(next_step.get("step_index") or 1),
                "should_escalate": bool(should_escalate),
                "reason": str(next_step.get("rationale") or ""),
                "retrieval_query": str(next_step.get("retrieval_query") or query),
                "execution_hint": execution_hint,
            }
        for row in result_rows:
            if str(row.get("source_type") or "") != "proof_packet":
                continue
            if not bool(row.get("is_current", True)):
                continue
            selection_rationale = str(
                row.get("selection_rationale")
                or _build_proof_packet_selection_rationale(
                    is_current=bool(row.get("is_current", True)),
                    support_strength=str(row.get("support_strength") or ""),
                    packet_version=int(row.get("packet_version") or 0),
                )
            )
            execution_hint = {
                "job_kind": "proof_retrieval_follow_up",
                "step_index": 1,
                "source_id": str(row.get("proof_id") or ""),
                "source_type": "proof_packet",
                "action_type": "reuse_current_packet",
                "label": str(row.get("title") or row.get("proof_id") or "Current proof packet"),
                "retrieval_query": query,
                "modules": [],
                "rationale": selection_rationale,
                "priority": 0,
            }
            return {
                "query": query,
                "action_type": "reuse_current_packet",
                "source_type": "proof_packet",
                "source_id": str(row.get("proof_id") or ""),
                "step_index": 1,
                "should_escalate": False,
                "reason": selection_rationale,
                "retrieval_query": query,
                "selection_rationale": selection_rationale,
                "packet_preference_summary": dict(row.get("packet_preference_summary") or {}),
                "execution_hint": execution_hint,
            }
        return {
            "query": query,
            "action_type": "none",
            "source_type": "",
            "source_id": "",
            "step_index": 0,
            "should_escalate": bool(should_escalate),
            "reason": "No follow-up action is currently available.",
            "retrieval_query": query,
            "execution_hint": {},
        }

    def _build_packet_candidates(
        self,
        result_rows: Sequence[Mapping[str, Any]],
        *,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for row in result_rows:
            if str(row.get("source_type") or "") != "proof_packet":
                continue
            candidates.append(
                {
                    "proof_id": str(row.get("proof_id") or ""),
                    "work_item_id": str(row.get("work_item_id") or ""),
                    "title": str(row.get("title") or ""),
                    "score": float(row.get("score") or 0.0),
                    "packet_version": int(row.get("packet_version") or 0),
                    "support_strength": str(row.get("support_strength") or ""),
                    "history_quality": int(row.get("history_quality") or 0),
                    "action_candidate_history_summary": dict(row.get("action_candidate_history_summary") or {}),
                    "packet_preference_summary": dict(row.get("packet_preference_summary") or {}),
                    "is_current": bool(row.get("is_current")),
                    "selection_rationale": str(row.get("selection_rationale") or ""),
                }
            )
        return candidates[:limit]

    def _build_action_candidates(
        self,
        *,
        query: str,
        follow_up_plan: Mapping[str, Any],
        packet_candidates: Sequence[Mapping[str, Any]],
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for packet in packet_candidates:
            proof_id = str(packet.get("proof_id") or "")
            if not proof_id:
                continue
            key = f"proof_packet:{proof_id}"
            if key in seen:
                continue
            candidates.append(
                {
                    "candidate_type": "proof_packet",
                    "action_type": "reuse_current_packet" if bool(packet.get("is_current")) else "refresh_local_support",
                    "source_type": "proof_packet",
                    "source_id": proof_id,
                    "label": str(packet.get("title") or proof_id),
                    "query": query,
                    "support_strength": str(packet.get("support_strength") or ""),
                    "priority": 0 if bool(packet.get("is_current")) else 1,
                    "selection_rationale": str(packet.get("selection_rationale") or ""),
                    "packet_preference_summary": dict(packet.get("packet_preference_summary") or {}),
                    "execution_hint": {
                        "job_kind": "proof_retrieval_follow_up",
                        "step_index": 1,
                        "source_id": proof_id,
                        "source_type": "proof_packet",
                        "action_type": "reuse_current_packet" if bool(packet.get("is_current")) else "refresh_local_support",
                        "label": str(packet.get("title") or proof_id),
                        "retrieval_query": query,
                        "modules": [],
                        "rationale": str(packet.get("selection_rationale") or ""),
                        "priority": 0 if bool(packet.get("is_current")) else 1,
                    },
                }
            )
            seen.add(key)
        for step in list(follow_up_plan.get("steps") or []):
            source_type = str(step.get("source_type") or "")
            source_id = str(step.get("source_id") or "")
            key = f"{source_type}:{source_id}"
            if key in seen:
                continue
            candidates.append(
                {
                    "candidate_type": "follow_up_step",
                    "action_type": str(step.get("action_type") or ""),
                    "source_type": source_type,
                    "source_id": source_id,
                    "label": str(step.get("label") or ""),
                    "query": query,
                    "support_strength": "",
                    "priority": int(step.get("priority") or 999),
                    "selection_rationale": str(step.get("rationale") or ""),
                    "execution_hint": {
                        "job_kind": "proof_retrieval_follow_up",
                        "step_index": int(step.get("step_index") or 1),
                        "source_id": source_id,
                        "source_type": source_type,
                        "action_type": str(step.get("action_type") or ""),
                        "label": str(step.get("label") or ""),
                        "retrieval_query": str(step.get("retrieval_query") or ""),
                        "modules": list(step.get("modules") or []),
                        "preferred_corpus_keys": list(step.get("preferred_corpus_keys") or []),
                        "preferred_corpus_priority": list(step.get("preferred_corpus_priority") or []),
                        "preferred_dataset_ids": list(step.get("preferred_dataset_ids") or []),
                        "preferred_dataset_priority": list(step.get("preferred_dataset_priority") or []),
                        "preferred_state_codes": list(step.get("preferred_state_codes") or []),
                        "routing_evidence": list(step.get("routing_evidence") or []),
                        "routing_reason": str(step.get("routing_reason") or ""),
                        "authority_backed": bool(step.get("authority_backed")),
                        "rationale": str(step.get("rationale") or ""),
                        "priority": int(step.get("priority") or 999),
                    },
                }
            )
            seen.add(key)
        candidates.sort(
            key=lambda item: (
                1 if str(item.get("action_type") or "") == "reuse_current_packet" else 0,
                _support_strength_rank(str(item.get("support_strength") or "")),
                -int(item.get("priority") or 999),
            ),
            reverse=True,
        )
        return candidates[:limit]

    def _make_plan(
        self,
        *,
        query: str,
        strategy: str,
        target: str,
        piece_ids: Sequence[str],
        rationale: str,
        priority: int,
        manifest: Dict[str, Any],
        stages: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> PackagedQueryExecutionPlan:
        cost_map = self._piece_cost_map(manifest)
        selected_piece_costs = {piece_id: int(cost_map.get(piece_id) or 1000) for piece_id in piece_ids}
        normalized_stages: List[Dict[str, Any]] = []
        for index, stage in enumerate(list(stages or []), start=1):
            stage_piece_ids = [str(piece_id) for piece_id in list(stage.get("piece_ids") or []) if str(piece_id).strip()]
            normalized_stages.append(
                {
                    "name": str(stage.get("name") or f"stage_{index}"),
                    "piece_ids": stage_piece_ids,
                    "estimated_cost": sum(int(cost_map.get(piece_id) or 1000) for piece_id in stage_piece_ids),
                    "purpose": str(stage.get("purpose") or ""),
                    "continue_on_success": bool(stage.get("continue_on_success")),
                    "result_policy": _jsonable(stage.get("result_policy") or {}),
                }
            )
        return PackagedQueryExecutionPlan(
            query=query,
            strategy=strategy,
            target=target,
            piece_ids=[str(piece_id) for piece_id in piece_ids],
            rationale=rationale,
            priority=int(priority),
            estimated_cost=sum(selected_piece_costs.values()),
            piece_costs=selected_piece_costs,
            stages=normalized_stages,
        )


def package_docket_dataset(
    dataset: Any,
    output_dir: str | Path,
    *,
    package_name: str | None = None,
    include_car: bool = True,
) -> Dict[str, Any]:
    """Package a docket dataset into linked Parquet and CAR bundle artifacts."""

    return DocketDatasetPackager().package(
        dataset,
        output_dir,
        package_name=package_name,
        include_car=include_car,
    )


def load_packaged_docket_dataset(manifest_path: str | Path) -> Dict[str, Any]:
    """Load a packaged docket dataset from its bundle manifest."""

    return DocketDatasetPackager().load_package(manifest_path)


def load_packaged_docket_dataset_components(
    manifest_path: str | Path,
    *,
    piece_ids: Optional[Sequence[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Load selected package components without rebuilding the full dataset."""

    return DocketDatasetPackager().load_package_components(manifest_path, piece_ids=piece_ids)


def load_packaged_docket_summary_view(manifest_path: str | Path) -> Dict[str, Any]:
    """Load a lightweight packaged docket summary view without document rows."""

    return DocketDatasetPackager().load_summary_view(manifest_path)


def load_packaged_docket_inspection_report(
    manifest_path: str | Path,
    *,
    report_format: str = "parsed",
) -> Any:
    """Load the archived packaged inspection report artifact."""

    return DocketDatasetPackager().load_inspection_report(
        manifest_path,
        report_format=report_format,
    )


def inspect_packaged_docket_bundle(manifest_path: str | Path) -> Dict[str, Any]:
    """Return a lightweight inspection view for a packaged docket bundle."""

    return DocketDatasetPackager().inspect_packaged_bundle(manifest_path)


def render_packaged_docket_inspection_report(
    manifest_path: str | Path,
    *,
    report_format: str = "markdown",
) -> str:
    """Render a bundled docket inspection/provenance report."""

    return DocketDatasetPackager().render_packaged_inspection_report(
        manifest_path,
        report_format=report_format,
    )


def iter_packaged_docket_chain(manifest_path: str | Path) -> List[Dict[str, Any]]:
    """Return package pieces in chain-load order."""

    return DocketDatasetPackager().iter_piece_chain(manifest_path)


def search_packaged_docket_dataset_bm25(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search packaged docket BM25 documents without rebuilding the full dataset."""

    return PackagedDocketQueryAdapter(manifest_path).search_bm25(query, top_k=top_k)


def search_packaged_docket_dataset_vector(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search packaged docket vector items without rebuilding the full dataset."""

    return PackagedDocketQueryAdapter(manifest_path).search_vector(query, top_k=top_k)


def search_packaged_docket_proof_tasks(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search packaged proof agenda and tactician plans without rebuilding the full dataset."""

    return PackagedDocketQueryAdapter(manifest_path).search_proof_tasks(query, top_k=top_k)


def get_packaged_docket_proof_revalidation_queue(
    manifest_path: str | Path,
    *,
    top_k: int = 10,
    min_priority: str = "low",
    include_execution_hints: bool = True,
    action_top_k: int = 10,
) -> Dict[str, Any]:
    """Return proof-assistant work items that currently need revalidation."""

    package_view = load_packaged_docket_dataset(manifest_path)
    agenda = _sort_proof_agenda_items((package_view.get("proof_assistant") or {}).get("agenda") or [])
    proof_store = dict(((package_view.get("proof_assistant") or {}).get("proof_store") or {}).get("proofs") or {})
    minimum_rank = _proof_revalidation_priority_rank(min_priority)
    queue_items: List[Dict[str, Any]] = []

    def _build_queue_query(item: Mapping[str, Any]) -> str:
        proof_payload = dict(proof_store.get(str(item.get("current_proof_packet_id") or "")) or {})
        stored_query = str(proof_payload.get("query") or "").strip()
        if stored_query:
            return stored_query
        parts = [
            str(item.get("title") or "").strip(),
            str(item.get("action") or "").strip(),
            str(item.get("party") or "").strip(),
            str(item.get("modality") or "").strip(),
        ]
        return " ".join(part for part in parts if part).strip()

    def _select_revalidation_action(
        query_result: Mapping[str, Any],
        queue_query: str,
        proof_payload: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        escalation = dict(query_result.get("escalation") or {})
        for candidate in list(escalation.get("action_candidates") or []):
            candidate_dict = dict(candidate or {})
            if str(candidate_dict.get("action_type") or "") == "reuse_current_packet":
                continue
            if str(candidate_dict.get("source_type") or "") == "proof_packet":
                continue
            candidate_dict.setdefault("query", queue_query)
            return candidate_dict
        next_action = dict(escalation.get("next_action_summary") or {})
        if next_action and str(next_action.get("source_type") or "") != "proof_packet":
            return {
                "query": queue_query,
                "action_type": str(next_action.get("action_type") or ""),
                "source_type": str(next_action.get("source_type") or ""),
                "source_id": str(next_action.get("source_id") or ""),
                "selection_rationale": str(next_action.get("selection_rationale") or next_action.get("reason") or ""),
                "execution_hint": dict(next_action.get("execution_hint") or {}),
                "support_strength": str(next_action.get("support_strength") or ""),
            }
        history = dict((proof_payload or {}).get("action_candidate_history") or {})
        ranked_history_candidates: List[Tuple[Tuple[int, int, int], Dict[str, Any]]] = []
        for execution in list(history.get("candidate_executions") or []):
            action_candidate = dict((dict(execution or {}).get("action_candidate") or {}))
            if not action_candidate:
                continue
            if str(action_candidate.get("action_type") or "") == "reuse_current_packet":
                continue
            if str(action_candidate.get("source_type") or "") == "proof_packet":
                continue
            candidate_summary = dict((dict(execution or {}).get("candidate_execution_summary") or {}))
            successful_summary = dict((dict(execution or {}).get("successful_action_summary") or {}))
            terminal_source_type = str(
                successful_summary.get("source_type")
                or candidate_summary.get("terminal_source_type")
                or ""
            )
            terminal_support_strength = str(
                successful_summary.get("support_strength")
                or candidate_summary.get("terminal_support_strength")
                or ""
            )
            action_candidate.setdefault("query", queue_query)
            ranked_history_candidates.append(
                (
                    (
                        _support_strength_priority(terminal_support_strength),
                        1 if terminal_source_type == "legal_dataset_parser" else 0,
                        1 if str(action_candidate.get("source_type") or "") == "legal_dataset_parser" else 0,
                    ),
                    action_candidate,
                )
            )
        if ranked_history_candidates:
            ranked_history_candidates.sort(key=lambda pair: pair[0], reverse=True)
            return dict(ranked_history_candidates[0][1])
        return {}

    for item in agenda:
        priority = str(item.get("proof_revalidation_priority") or "")
        if not bool(item.get("current_proof_packet_review_required")):
            continue
        if _proof_revalidation_priority_rank(priority) < minimum_rank:
            continue
        queue_query = _build_queue_query(item)
        queue_entry = {
            "work_item_id": str(item.get("work_item_id") or ""),
            "title": str(item.get("title") or ""),
            "party": str(item.get("party") or ""),
            "action": str(item.get("action") or ""),
            "modality": str(item.get("modality") or ""),
            "current_proof_packet_id": str(item.get("current_proof_packet_id") or ""),
            "current_proof_packet_version": int(item.get("current_proof_packet_version") or 0),
            "current_proof_packet_support_strength": str(item.get("current_proof_packet_support_strength") or ""),
            "proof_revalidation_status": str(item.get("proof_revalidation_status") or ""),
            "proof_revalidation_priority": priority,
            "current_proof_packet_review_required": True,
            "current_proof_packet_review_trigger": (
                dict(item.get("current_proof_packet_review_trigger") or {})
                if isinstance(item.get("current_proof_packet_review_trigger"), Mapping)
                else {}
            ),
            "attached_evidence_count": int(item.get("attached_evidence_count") or 0),
            "selection_rationale": (
                "Queued because the current proof packet changed preferred support and needs revalidation."
            ),
            "revalidation_query": queue_query,
        }
        if include_execution_hints and queue_query:
            proof_payload = dict(proof_store.get(str(item.get("current_proof_packet_id") or "")) or {})
            query_result = execute_packaged_docket_query(
                manifest_path,
                queue_query,
                top_k=action_top_k,
            )
            recommended_action = _select_revalidation_action(query_result, queue_query, proof_payload)
            queue_entry["recommended_revalidation_action"] = recommended_action
            queue_entry["recommended_revalidation_execution_hint"] = dict(
                recommended_action.get("execution_hint") or {}
            )
            queue_entry["recommended_revalidation_action_count"] = len(
                list((dict(query_result.get("escalation") or {})).get("action_candidates") or [])
            )
        else:
            queue_entry["recommended_revalidation_action"] = {}
            queue_entry["recommended_revalidation_execution_hint"] = {}
            queue_entry["recommended_revalidation_action_count"] = 0
        queue_items.append(queue_entry)
    limited_items = queue_items[:top_k]
    summary = {
        "queue_count": len(limited_items),
        "total_review_required_work_item_count": len(queue_items),
        "high_priority_revalidation_count": sum(
            1
            for item in queue_items
            if _proof_revalidation_priority_rank(str(item.get("proof_revalidation_priority") or "")) >= 3
        ),
        "min_priority": str(min_priority or ""),
        "execution_hints_included": bool(include_execution_hints),
    }
    return {
        "top_k": top_k,
        "min_priority": str(min_priority or ""),
        "include_execution_hints": bool(include_execution_hints),
        "results": limited_items,
        "result_count": len(limited_items),
        "summary": summary,
        "source": "packaged_proof_revalidation_queue",
    }


def search_packaged_docket_logic_artifacts(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Search packaged temporal, DCEC, and frame artifacts without rebuilding the full dataset."""

    return PackagedDocketQueryAdapter(manifest_path).search_logic_artifacts(query, top_k=top_k)


def plan_packaged_docket_query(
    manifest_path: str | Path,
    query: str,
) -> Dict[str, Any]:
    """Build a manifest-aware execution plan for a packaged docket query."""

    return PackagedDocketQueryAdapter(manifest_path).plan_query(query).to_dict()


def execute_packaged_docket_query(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
    include_action_candidate_comparison: bool = False,
    action_candidate_limit: Optional[int] = None,
    action_candidates_chain_until_satisfied: bool = False,
) -> Dict[str, Any]:
    """Plan and execute a packaged docket query against the narrowest relevant pieces."""

    adapter = PackagedDocketQueryAdapter(manifest_path)
    plan = adapter.plan_query(query)
    if plan.target == "logic_artifacts":
        result = adapter.search_logic_artifacts(query, top_k=top_k, piece_ids=plan.piece_ids)
        result["execution_plan"] = plan.to_dict()
        result["execution_stages"] = [
            {
                "stage_index": 1,
                "stage_name": "logic_artifacts",
                "piece_ids": list(plan.piece_ids),
                "estimated_cost": int(plan.estimated_cost or 0),
                "result_count": int(result.get("result_count") or 0),
                "cumulative_result_count": int(result.get("result_count") or 0),
                "source": str(result.get("source") or ""),
                "result_policy": {"merge_mode": "by_artifact"},
            }
        ]
        result["stages_executed"] = 1
        result["escalation"] = adapter._build_escalation_guidance(
            plan,
            result,
            execution_stages=result["execution_stages"],
            top_k=top_k,
        )
        result["proof_preference_summary"] = dict((result.get("escalation") or {}).get("proof_preference_summary") or {})
        result["proof_preference_history_summary"] = dict((result.get("escalation") or {}).get("proof_preference_history_summary") or {})
        result["proof_preference_review_trigger"] = dict((result.get("escalation") or {}).get("proof_preference_review_trigger") or {})
        if include_action_candidate_comparison:
            result = _attach_action_candidate_comparison(
                manifest_path,
                result,
                top_k=top_k,
                limit=action_candidate_limit,
                chain_until_satisfied=action_candidates_chain_until_satisfied,
            )
        return result
    result = adapter.execute_plan(plan, top_k=top_k)
    result["proof_preference_summary"] = dict((result.get("escalation") or {}).get("proof_preference_summary") or {})
    result["proof_preference_history_summary"] = dict((result.get("escalation") or {}).get("proof_preference_history_summary") or {})
    result["proof_preference_review_trigger"] = dict((result.get("escalation") or {}).get("proof_preference_review_trigger") or {})
    if include_action_candidate_comparison:
        result = _attach_action_candidate_comparison(
            manifest_path,
            result,
            top_k=top_k,
            limit=action_candidate_limit,
            chain_until_satisfied=action_candidates_chain_until_satisfied,
        )
    return result


def prepare_packaged_docket_follow_up_job(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
    step_index: int = 1,
) -> Dict[str, Any]:
    """Materialize an actionable retrieval job from packaged escalation guidance."""

    execution = execute_packaged_docket_query(manifest_path, query, top_k=top_k)
    escalation = dict(execution.get("escalation") or {})
    follow_up_plan = dict(escalation.get("follow_up_plan") or {})
    steps = [dict(step) for step in list(follow_up_plan.get("steps") or [])]
    if not bool(escalation.get("should_escalate")):
        reuse_step = _build_reuse_current_packet_step(execution, query=query)
        if reuse_step:
            return {
                "query": query,
                "job_ready": True,
                "reason": "A current packaged proof packet already covers this query and can be reused directly.",
                "source_type": str(reuse_step.get("source_type") or ""),
                "action_type": str(reuse_step.get("action_type") or ""),
                "job": {
                    "job_kind": "proof_retrieval_follow_up",
                    "step_index": int(reuse_step.get("step_index") or 1),
                    "source_id": str(reuse_step.get("source_id") or ""),
                    "source_type": str(reuse_step.get("source_type") or ""),
                    "action_type": str(reuse_step.get("action_type") or ""),
                    "label": str(reuse_step.get("label") or ""),
                    "retrieval_query": str(reuse_step.get("retrieval_query") or query),
                    "modules": list(reuse_step.get("modules") or []),
                    "preferred_corpus_keys": list(reuse_step.get("preferred_corpus_keys") or []),
                    "preferred_corpus_priority": list(reuse_step.get("preferred_corpus_priority") or []),
                    "preferred_dataset_ids": list(reuse_step.get("preferred_dataset_ids") or []),
                    "preferred_dataset_priority": list(reuse_step.get("preferred_dataset_priority") or []),
                    "preferred_state_codes": list(reuse_step.get("preferred_state_codes") or []),
                    "routing_evidence": list(reuse_step.get("routing_evidence") or []),
                    "routing_reason": str(reuse_step.get("routing_reason") or ""),
                    "authority_backed": bool(reuse_step.get("authority_backed")),
                    "rationale": str(reuse_step.get("rationale") or ""),
                    "priority": int(reuse_step.get("priority") or 1),
                },
                "available_steps": [reuse_step],
                "execution": execution,
            }
    if not bool(escalation.get("should_escalate")) or not steps:
        return {
            "query": query,
            "job_ready": False,
            "reason": str(escalation.get("reason") or "No follow-up job is required."),
            "source_type": "",
            "action_type": "",
            "job": {},
            "available_steps": [],
            "execution": execution,
        }

    normalized_index = max(1, int(step_index)) - 1
    selected_step = dict(steps[min(normalized_index, len(steps) - 1)])
    return {
        "query": query,
        "job_ready": True,
        "reason": str(escalation.get("reason") or ""),
        "source_type": str(selected_step.get("source_type") or ""),
        "action_type": str(selected_step.get("action_type") or ""),
        "job": {
            "job_kind": "proof_retrieval_follow_up",
            "step_index": int(selected_step.get("step_index") or (normalized_index + 1)),
            "source_id": str(selected_step.get("source_id") or ""),
            "source_type": str(selected_step.get("source_type") or ""),
            "action_type": str(selected_step.get("action_type") or ""),
            "label": str(selected_step.get("label") or ""),
            "retrieval_query": str(selected_step.get("retrieval_query") or query),
            "modules": list(selected_step.get("modules") or []),
            "preferred_corpus_keys": list(selected_step.get("preferred_corpus_keys") or []),
            "preferred_corpus_priority": list(selected_step.get("preferred_corpus_priority") or []),
            "preferred_dataset_ids": list(selected_step.get("preferred_dataset_ids") or []),
            "preferred_dataset_priority": list(selected_step.get("preferred_dataset_priority") or []),
            "preferred_state_codes": list(selected_step.get("preferred_state_codes") or []),
            "routing_evidence": list(selected_step.get("routing_evidence") or []),
            "routing_reason": str(selected_step.get("routing_reason") or ""),
            "authority_backed": bool(selected_step.get("authority_backed")),
            "rationale": str(selected_step.get("rationale") or ""),
            "priority": int(selected_step.get("priority") or (normalized_index + 1)),
        },
        "available_steps": steps,
        "execution": execution,
    }


def execute_packaged_docket_follow_up_job(
    manifest_path: str | Path,
    follow_up_job: Optional[Mapping[str, Any]] = None,
    *,
    query: Optional[str] = None,
    top_k: int = 10,
    step_index: int = 1,
) -> Dict[str, Any]:
    """Execute a lightweight local follow-up retrieval job from packaged escalation guidance."""

    prepared = dict(follow_up_job or {})
    if not prepared:
        if not str(query or "").strip():
            return {
                "job_ready": False,
                "executed": False,
                "reason": "Either a follow-up job or a query is required.",
                "results": [],
                "result_count": 0,
            }
        prepared = prepare_packaged_docket_follow_up_job(
            manifest_path,
            str(query),
            top_k=top_k,
            step_index=step_index,
        )

    job = dict(prepared.get("job") or {})
    if not bool(prepared.get("job_ready")) or not job:
        return {
            "job_ready": False,
            "executed": False,
            "reason": str(prepared.get("reason") or "No executable follow-up job is available."),
            "results": [],
            "result_count": 0,
            "job": job,
        }

    source_type = str(job.get("source_type") or "")
    action_type = str(job.get("action_type") or "")
    if not action_type:
        action_type = _default_follow_up_action_type(source_type)
    retrieval_query = str(job.get("retrieval_query") or query or "")
    packager = DocketDatasetPackager()
    if source_type == "authority_list":
        rows = packager.load_package_piece(manifest_path, "authorities")
        results = _search_packaged_follow_up_rows(rows, retrieval_query, top_k=top_k)
        return {
            "job_ready": True,
            "executed": True,
            "source_type": source_type,
            "action_type": action_type,
            "job": job,
            "results": results,
            "result_count": len(results),
            "source": "packaged_authorities",
        }
    if source_type == "local_docket_documents":
        rows = packager.load_package_piece(manifest_path, "documents")
        results = _search_packaged_follow_up_rows(rows, retrieval_query, top_k=top_k)
        return {
            "job_ready": True,
            "executed": True,
            "source_type": source_type,
            "action_type": action_type,
            "job": job,
            "results": results,
            "result_count": len(results),
            "source": "packaged_documents",
        }
    if source_type == "local_bm25_index":
        result = PackagedDocketQueryAdapter(manifest_path).search_bm25(
            retrieval_query,
            top_k=top_k,
            piece_ids=["bm25_documents", "documents"],
        )
        return {
            "job_ready": True,
            "executed": True,
            "source_type": source_type,
            "action_type": action_type,
            "job": job,
            "results": list(result.get("results") or []),
            "result_count": int(result.get("result_count") or 0),
            "source": str(result.get("source") or "packaged_bm25_documents"),
        }
    if source_type == "local_vector_index":
        result = PackagedDocketQueryAdapter(manifest_path).search_vector(
            retrieval_query,
            top_k=top_k,
            piece_ids=["vector_items"],
        )
        return {
            "job_ready": True,
            "executed": True,
            "source_type": source_type,
            "action_type": action_type,
            "job": job,
            "results": list(result.get("results") or []),
            "result_count": int(result.get("result_count") or 0),
            "source": str(result.get("source") or "packaged_vector_items"),
        }
    if source_type == "proof_packet":
        proof_store_rows = packager.load_package_piece(manifest_path, "proof_store_entries")
        packets = packager.load_package_piece(manifest_path, "proof_evidence_packets")
        source_id = str(job.get("source_id") or "")
        packet_summary = next(
            (dict(item) for item in packets if str(item.get("proof_id") or "") == source_id),
            {},
        )
        if str(job.get("action_type") or "").strip() == "":
            action_type = (
                "reuse_current_packet"
                if bool(packet_summary.get("is_current", True))
                else "refresh_local_support"
            )
        matched_row = None
        for row in proof_store_rows:
            if str(row.get("proof_id") or "") == source_id:
                matched_row = dict(row)
                break
        if matched_row is None:
            packet_ids = {str(item.get("proof_id") or "") for item in packets if str(item.get("proof_id") or "")}
            if source_id and source_id not in packet_ids:
                rebuilt = load_packaged_docket_dataset(manifest_path)
                rebuilt_proofs = dict(((rebuilt.get("proof_assistant") or {}).get("proof_store") or {}).get("proofs") or {})
                rebuilt_payload = dict(rebuilt_proofs.get(source_id) or {})
                if not rebuilt_payload:
                    return {
                        "job_ready": True,
                        "executed": False,
                        "source_type": source_type,
                        "action_type": action_type,
                        "job": job,
                        "reason": "The requested stored proof packet is not present in this packaged bundle.",
                        "results": [],
                        "result_count": 0,
                    }
                proof_payload = rebuilt_payload
            else:
                proof_payload = {}
        else:
            proof_payload = dict(packager._parse_possible_json((matched_row or {}).get("payload_json")) or {})
        evidence_bundle = dict(proof_payload.get("evidence_bundle") or {})
        evidence_items = [dict(item) for item in list(evidence_bundle.get("evidence_items") or [])]
        return {
            "job_ready": True,
            "executed": True,
            "source_type": source_type,
            "action_type": action_type,
            "job": job,
            "results": evidence_items[:top_k],
            "result_count": min(len(evidence_items), top_k),
            "source": "packaged_proof_packet",
            "proof_packet": {
                "proof_id": str(proof_payload.get("proof_id") or source_id),
                "work_item_id": str(proof_payload.get("work_item_id") or ""),
                "packet_version": int(proof_payload.get("packet_version") or packet_summary.get("packet_version") or 0),
                "is_current": bool(proof_payload.get("is_current", packet_summary.get("is_current", True))),
                "superseded": bool(proof_payload.get("superseded", packet_summary.get("superseded", False))),
                "superseded_by_proof_id": str(
                    proof_payload.get("superseded_by_proof_id") or packet_summary.get("superseded_by_proof_id") or ""
                ),
                "status": str(proof_payload.get("status") or ""),
                "matched_plan": dict(proof_payload.get("matched_plan") or {}),
                "evidence_bundle": evidence_bundle,
            },
        }
    if source_type == "legal_dataset_parser":
        adapter = _prepare_legal_dataset_parser_adapter(job, retrieval_query, top_k=top_k)
        if bool(adapter.get("adapter_ready")):
            dispatch = {
                "dispatch_kind": "legal_dataset_parser_request",
                "source_id": str(job.get("source_id") or ""),
                "source_type": source_type,
                "retrieval_query": retrieval_query,
                "modules": list(job.get("modules") or []),
                "preferred_corpus_keys": list(job.get("preferred_corpus_keys") or []),
                "preferred_corpus_priority": list(job.get("preferred_corpus_priority") or []),
                "preferred_dataset_ids": list(job.get("preferred_dataset_ids") or []),
                "preferred_dataset_priority": list(job.get("preferred_dataset_priority") or []),
                "preferred_state_codes": list(job.get("preferred_state_codes") or []),
                "routing_evidence": list(job.get("routing_evidence") or []),
                "routing_reason": str(job.get("routing_reason") or ""),
                "authority_backed": bool(job.get("authority_backed")),
                "priority": int(job.get("priority") or 0),
                "adapter": adapter,
            }
            execution = _execute_legal_dataset_parser_adapter(adapter)
            if bool(execution.get("executed")):
                return {
                    "job_ready": True,
                    "executed": True,
                    "dispatched": True,
                    "source_type": source_type,
                    "action_type": action_type,
                    "job": job,
                    "source": "legal_dataset_parser_execution",
                    "adapter": adapter,
                    "dispatch": dispatch,
                    "reason": str(
                        execution.get("reason")
                        or "Executed the legal dataset parser follow-up adapter."
                    ),
                    "results": list(execution.get("results") or []),
                    "result_count": int(execution.get("result_count") or 0),
                    "parser_result": execution.get("parser_result") or {},
                }
            return {
                "job_ready": True,
                "executed": True,
                "dispatched": True,
                "source_type": source_type,
                "action_type": action_type,
                "job": job,
                "source": "legal_dataset_parser_adapter",
                "adapter": adapter,
                "dispatch": dispatch,
                "reason": "Prepared an executable legal dataset parser adapter for the follow-up step.",
                "results": [],
                "result_count": 0,
            }
        return {
            "job_ready": True,
            "executed": False,
            "dispatched": True,
            "source_type": source_type,
            "action_type": action_type,
            "job": job,
            "dispatch": {
                "dispatch_kind": "legal_dataset_parser_request",
                "source_id": str(job.get("source_id") or ""),
                "source_type": source_type,
                "retrieval_query": retrieval_query,
                "modules": list(job.get("modules") or []),
                "preferred_corpus_keys": list(job.get("preferred_corpus_keys") or []),
                "preferred_corpus_priority": list(job.get("preferred_corpus_priority") or []),
                "preferred_dataset_ids": list(job.get("preferred_dataset_ids") or []),
                "preferred_dataset_priority": list(job.get("preferred_dataset_priority") or []),
                "preferred_state_codes": list(job.get("preferred_state_codes") or []),
                "routing_evidence": list(job.get("routing_evidence") or []),
                "routing_reason": str(job.get("routing_reason") or ""),
                "authority_backed": bool(job.get("authority_backed")),
                "priority": int(job.get("priority") or 0),
            },
            "reason": "This follow-up step is ready for parser-backed execution but is not executed inside the packaged bundle.",
            "results": [],
            "result_count": 0,
        }
    return {
        "job_ready": True,
        "executed": False,
        "source_type": source_type,
        "action_type": action_type,
        "job": job,
        "reason": "This follow-up source type is not yet executable locally.",
        "results": [],
        "result_count": 0,
    }


def execute_packaged_docket_next_action(
    manifest_path: str | Path,
    next_action: Optional[Mapping[str, Any]] = None,
    *,
    query_result: Optional[Mapping[str, Any]] = None,
    query: Optional[str] = None,
    top_k: int = 10,
    chain_until_satisfied: bool = False,
) -> Dict[str, Any]:
    """Execute a proof-query next-action summary or its execution hint directly."""

    summary = dict(next_action or {})
    if not summary and query_result:
        escalation = dict((dict(query_result).get("escalation") or {}))
        summary = dict(escalation.get("next_action_summary") or {})
    execution_hint = dict(summary.get("execution_hint") or {})
    if not execution_hint:
        return {
            "job_ready": False,
            "executed": False,
            "action_type": str(summary.get("action_type") or ""),
            "source_type": str(summary.get("source_type") or ""),
            "reason": str(summary.get("reason") or "No execution hint is available for this next action."),
            "results": [],
            "result_count": 0,
            "next_action_summary": summary,
        }
    prepared = {
        "job_ready": True,
        "source_type": str(execution_hint.get("source_type") or summary.get("source_type") or ""),
        "action_type": str(execution_hint.get("action_type") or summary.get("action_type") or ""),
        "job": {
            "job_kind": str(execution_hint.get("job_kind") or "proof_retrieval_follow_up"),
            "step_index": int(execution_hint.get("step_index") or summary.get("step_index") or 1),
            "source_id": str(execution_hint.get("source_id") or summary.get("source_id") or ""),
            "source_type": str(execution_hint.get("source_type") or summary.get("source_type") or ""),
            "action_type": str(execution_hint.get("action_type") or summary.get("action_type") or ""),
            "label": str(execution_hint.get("label") or ""),
            "retrieval_query": str(execution_hint.get("retrieval_query") or summary.get("retrieval_query") or query or ""),
            "modules": list(execution_hint.get("modules") or []),
            "preferred_corpus_keys": list(execution_hint.get("preferred_corpus_keys") or []),
            "preferred_corpus_priority": list(execution_hint.get("preferred_corpus_priority") or []),
            "preferred_dataset_ids": list(execution_hint.get("preferred_dataset_ids") or []),
            "preferred_dataset_priority": list(execution_hint.get("preferred_dataset_priority") or []),
            "preferred_state_codes": list(execution_hint.get("preferred_state_codes") or []),
            "routing_evidence": list(execution_hint.get("routing_evidence") or []),
            "routing_reason": str(execution_hint.get("routing_reason") or ""),
            "authority_backed": bool(execution_hint.get("authority_backed")),
            "rationale": str(execution_hint.get("rationale") or summary.get("reason") or ""),
            "priority": int(execution_hint.get("priority") or 1),
        },
    }
    execution = execute_packaged_docket_follow_up_job(
        manifest_path,
        prepared,
        query=query,
        top_k=top_k,
    )
    execution["next_action_summary"] = summary
    execution["execution_hint"] = execution_hint
    query_text = str(summary.get("query") or query or "")
    if (
        bool(chain_until_satisfied)
        and query_text
        and not _follow_up_execution_satisfied(execution, top_k=top_k)
    ):
        start_step_index = max(1, int(summary.get("step_index") or execution_hint.get("step_index") or 1))
        chained = execute_packaged_docket_follow_up_plan(
            manifest_path,
            query_text,
            top_k=top_k,
            start_step_index=start_step_index,
        )
        execution["auto_chained"] = True
        execution["chain_until_satisfied"] = True
        execution["chained_execution"] = chained
        execution["successful_action_summary"] = _build_successful_action_summary(
            chained.get("final_execution") or {},
            fallback_query=query_text,
        )
    else:
        execution["auto_chained"] = False
        execution["chain_until_satisfied"] = bool(chain_until_satisfied)
        execution["successful_action_summary"] = _build_successful_action_summary(
            execution,
            fallback_query=query_text,
        )
    return execution


def execute_packaged_docket_action_candidate(
    manifest_path: str | Path,
    action_candidate: Mapping[str, Any],
    *,
    query: Optional[str] = None,
    top_k: int = 10,
    chain_until_satisfied: bool = False,
) -> Dict[str, Any]:
    """Execute a ranked escalation action candidate via its embedded execution hint."""

    candidate = dict(action_candidate or {})
    execution_hint = dict(candidate.get("execution_hint") or {})
    if not execution_hint:
        return {
            "job_ready": False,
            "executed": False,
            "reason": "This action candidate does not include an execution hint.",
            "action_candidate": candidate,
            "results": [],
            "result_count": 0,
        }
    execution = execute_packaged_docket_next_action(
        manifest_path,
        next_action={
            "query": str(candidate.get("query") or query or execution_hint.get("retrieval_query") or ""),
            "action_type": str(candidate.get("action_type") or execution_hint.get("action_type") or ""),
            "source_type": str(candidate.get("source_type") or execution_hint.get("source_type") or ""),
            "source_id": str(candidate.get("source_id") or execution_hint.get("source_id") or ""),
            "reason": str(candidate.get("selection_rationale") or execution_hint.get("rationale") or ""),
            "retrieval_query": str(execution_hint.get("retrieval_query") or query or ""),
            "execution_hint": execution_hint,
        },
        query=query,
        top_k=top_k,
        chain_until_satisfied=chain_until_satisfied,
    )
    execution["action_candidate"] = candidate
    execution["candidate_execution_summary"] = _build_candidate_execution_summary(
        candidate,
        execution,
    )
    return execution


def execute_packaged_docket_action_candidates(
    manifest_path: str | Path,
    action_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    query_result: Optional[Mapping[str, Any]] = None,
    query: Optional[str] = None,
    top_k: int = 10,
    limit: Optional[int] = None,
    chain_until_satisfied: bool = False,
) -> Dict[str, Any]:
    """Execute ranked action candidates and return an enriched comparison view."""

    candidates = [dict(item) for item in list(action_candidates or [])]
    if not candidates and query_result:
        escalation = dict((dict(query_result).get("escalation") or {}))
        candidates = [dict(item) for item in list(escalation.get("action_candidates") or [])]
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]
    query_text = str(query or "")
    if not query_text and query_result:
        query_text = str(dict(query_result).get("query") or "")

    executions: List[Dict[str, Any]] = []
    for candidate in candidates:
        execution = execute_packaged_docket_action_candidate(
            manifest_path,
            candidate,
            query=query_text,
            top_k=top_k,
            chain_until_satisfied=chain_until_satisfied,
        )
        executions.append(execution)

    comparison_rows = [
        _build_action_candidate_execution_row(execution)
        for execution in executions
    ]
    ranked_pairs = sorted(
        list(zip(executions, comparison_rows)),
        key=lambda pair: (
            0 if bool(pair[0].get("executed")) else 1,
            -_support_strength_priority(pair[1].get("terminal_support_strength")),
            0 if bool(pair[1].get("resolved_directly")) else 1,
            int(pair[1].get("terminal_result_count") or 0) * -1,
        ),
    )
    best_execution = dict(ranked_pairs[0][0]) if ranked_pairs and bool(ranked_pairs[0][0].get("executed")) else {}
    best_summary = dict(ranked_pairs[0][1]) if ranked_pairs and bool(ranked_pairs[0][0].get("executed")) else {}
    return {
        "query": query_text,
        "candidate_count": len(candidates),
        "executed_candidate_count": sum(1 for execution in executions if bool(execution.get("executed"))),
        "chain_until_satisfied": bool(chain_until_satisfied),
        "comparison_mode": "chain_until_satisfied" if bool(chain_until_satisfied) else "single_step",
        "candidate_executions": executions,
        "candidate_comparison": comparison_rows,
        "best_candidate_execution": best_execution,
        "best_candidate_summary": best_summary,
        "best_terminal_candidate_summary": best_summary,
    }


def _attach_action_candidate_comparison(
    manifest_path: str | Path,
    result: Mapping[str, Any],
    *,
    top_k: int,
    limit: Optional[int],
    chain_until_satisfied: bool,
) -> Dict[str, Any]:
    enriched = dict(result)
    escalation = dict(enriched.get("escalation") or {})
    if not list(escalation.get("action_candidates") or []):
        escalation["executed_action_candidates"] = {
            "query": str(enriched.get("query") or ""),
            "candidate_count": 0,
            "executed_candidate_count": 0,
            "chain_until_satisfied": bool(chain_until_satisfied),
            "comparison_mode": "chain_until_satisfied" if bool(chain_until_satisfied) else "single_step",
            "candidate_executions": [],
            "candidate_comparison": [],
            "best_candidate_execution": {},
            "best_candidate_summary": {},
            "best_terminal_candidate_summary": {},
        }
        enriched["escalation"] = escalation
        return enriched

    escalation["executed_action_candidates"] = execute_packaged_docket_action_candidates(
        manifest_path,
        query_result=enriched,
        top_k=top_k,
        limit=limit,
        chain_until_satisfied=chain_until_satisfied,
    )
    enriched["escalation"] = escalation
    return enriched


def _build_query_proof_preference_summary(
    *,
    query: str,
    result_rows: Sequence[Mapping[str, Any]],
    next_action_summary: Mapping[str, Any],
    should_escalate: bool,
) -> Dict[str, Any]:
    rows = [dict(item) for item in list(result_rows or [])]
    packet_rows = [row for row in rows if str(row.get("source_type") or "") == "proof_packet"]
    if packet_rows:
        chosen = dict(packet_rows[0])
        preference_summary = dict(chosen.get("packet_preference_summary") or {})
        return {
            "query": str(query or ""),
            "preferred_source_type": "proof_packet",
            "preferred_source_id": str(chosen.get("proof_id") or ""),
            "preferred_action_type": "reuse_current_packet" if bool(chosen.get("is_current", True)) else "refresh_local_support",
            "should_escalate": bool(should_escalate),
            "selection_rationale": str(chosen.get("selection_rationale") or ""),
            "packet_preference_summary": preference_summary,
        }
    next_summary = dict(next_action_summary or {})
    return {
        "query": str(query or ""),
        "preferred_source_type": str(next_summary.get("source_type") or ""),
        "preferred_source_id": str(next_summary.get("source_id") or ""),
        "preferred_action_type": str(next_summary.get("action_type") or ""),
        "should_escalate": bool(should_escalate),
        "selection_rationale": str(next_summary.get("selection_rationale") or next_summary.get("reason") or ""),
        "packet_preference_summary": dict(next_summary.get("packet_preference_summary") or {}),
    }


def _build_query_proof_preference_history_summary(
    *,
    query: str,
    result_rows: Sequence[Mapping[str, Any]],
    proof_preference_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    rows = [dict(item) for item in list(result_rows or [])]
    packet_rows = [row for row in rows if str(row.get("source_type") or "") == "proof_packet"]
    preferred_source_type = str(proof_preference_summary.get("preferred_source_type") or "")
    if packet_rows and preferred_source_type == "proof_packet":
        chosen = dict(packet_rows[0])
        history = [dict(item) for item in list(chosen.get("preference_history") or [])]
        latest = dict(history[-1] if history else {})
        previous = dict(history[-2] if len(history) >= 2 else {})
        latest_terminal = str(latest.get("best_terminal_source_type") or "")
        previous_terminal = str(previous.get("best_terminal_source_type") or "")
        latest_strength = str(latest.get("best_terminal_support_strength") or "")
        previous_strength = str(previous.get("best_terminal_support_strength") or "")
        changed = bool(previous) and (
            latest_terminal != previous_terminal or latest_strength != previous_strength
        )
        return {
            "query": str(query or ""),
            "preferred_source_type": "proof_packet",
            "preferred_source_id": str(chosen.get("proof_id") or ""),
            "history_count": len(history),
            "latest_packet_version": int(latest.get("packet_version") or chosen.get("packet_version") or 0),
            "has_previous_preference": bool(previous),
            "stable_preference": bool(
                previous
                and latest_terminal == previous_terminal
                and latest_strength == previous_strength
            ) if previous else True,
            "changed_since_previous": changed,
            "change_summary": {
                "changed": changed,
                "previous_terminal_source_type": previous_terminal,
                "latest_terminal_source_type": latest_terminal,
                "previous_terminal_support_strength": previous_strength,
                "latest_terminal_support_strength": latest_strength,
            },
            "latest_preference": latest,
            "previous_preference": previous,
        }
    return {
        "query": str(query or ""),
        "preferred_source_type": preferred_source_type,
        "preferred_source_id": str(proof_preference_summary.get("preferred_source_id") or ""),
        "history_count": 0,
        "latest_packet_version": 0,
        "has_previous_preference": False,
        "stable_preference": False,
        "changed_since_previous": False,
        "change_summary": {
            "changed": False,
            "previous_terminal_source_type": "",
            "latest_terminal_source_type": "",
            "previous_terminal_support_strength": "",
            "latest_terminal_support_strength": "",
        },
        "latest_preference": {},
        "previous_preference": {},
    }


def _build_proof_preference_review_trigger(
    history_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    summary = dict(history_summary or {})
    change_summary = dict(summary.get("change_summary") or {})
    changed = bool(summary.get("changed_since_previous")) or bool(change_summary.get("changed"))
    latest_source = str(change_summary.get("latest_terminal_source_type") or "")
    previous_source = str(change_summary.get("previous_terminal_source_type") or "")
    latest_strength = str(change_summary.get("latest_terminal_support_strength") or "")
    previous_strength = str(change_summary.get("previous_terminal_support_strength") or "")
    source_changed = bool(previous_source and latest_source and previous_source != latest_source)
    strength_changed = bool(previous_strength and latest_strength and previous_strength != latest_strength)
    if source_changed:
        severity = "high"
    elif strength_changed:
        severity = "medium"
    else:
        severity = "low" if changed else "none"
    return {
        "review_required": changed,
        "trigger_type": "preference_shift_review" if changed else "",
        "severity": severity,
        "reason": (
            f"Preferred proof support changed from {previous_source or 'unknown'} / {previous_strength or 'unknown'} "
            f"to {latest_source or 'unknown'} / {latest_strength or 'unknown'}."
            if changed
            else "No proof preference change detected."
        ),
        "source_changed": source_changed,
        "support_strength_changed": strength_changed,
        "previous_terminal_source_type": previous_source,
        "latest_terminal_source_type": latest_source,
        "previous_terminal_support_strength": previous_strength,
        "latest_terminal_support_strength": latest_strength,
    }


def _build_agenda_revalidation_metadata(
    review_trigger: Mapping[str, Any],
) -> Dict[str, Any]:
    trigger = dict(review_trigger or {})
    review_required = bool(trigger.get("review_required"))
    severity = str(trigger.get("severity") or "none")
    return {
        "current_proof_packet_review_required": review_required,
        "current_proof_packet_review_trigger": trigger,
        "proof_revalidation_status": "needs_revalidation" if review_required else "current_support_stable",
        "proof_revalidation_priority": severity if review_required else "none",
    }


def _proof_revalidation_priority_rank(priority: str) -> int:
    return {
        "high": 3,
        "medium": 2,
        "low": 1,
        "none": 0,
    }.get(str(priority or "").lower(), 0)


def _sort_proof_agenda_items(
    agenda_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    normalized = [dict(item) for item in list(agenda_rows or [])]
    normalized.sort(
        key=lambda item: (
            _proof_revalidation_priority_rank(str(item.get("proof_revalidation_priority") or "")),
            1 if bool(item.get("current_proof_packet_review_required")) else 0,
            int(item.get("current_proof_packet_version") or 0),
            int(item.get("attached_evidence_count") or 0),
            str(item.get("title") or ""),
        ),
        reverse=True,
    )
    return normalized


def _count_agenda_revalidation_items(
    agenda_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, int]:
    rows = list(agenda_rows or [])
    return {
        "review_required_work_item_count": sum(
            1 for item in rows if bool(item.get("current_proof_packet_review_required"))
        ),
        "high_priority_revalidation_count": sum(
            1
            for item in rows
            if _proof_revalidation_priority_rank(str(item.get("proof_revalidation_priority") or "")) >= 3
        ),
    }


def _build_persisted_action_candidate_history(
    manifest_path: str | Path,
    query: str,
    *,
    execution: Mapping[str, Any],
    top_k: int,
) -> Dict[str, Any]:
    direct = dict(execution.get("executed_action_candidates") or {})
    if direct:
        return direct
    nested_execution = dict(execution.get("execution") or {})
    nested_escalation = dict(nested_execution.get("escalation") or {})
    nested = dict(nested_escalation.get("executed_action_candidates") or {})
    if nested:
        return nested
    if list(nested_escalation.get("action_candidates") or []):
        return execute_packaged_docket_action_candidates(
            manifest_path,
            query_result=nested_execution,
            query=query,
            top_k=top_k,
            chain_until_satisfied=True,
        )
    return {
        "query": str(query or ""),
        "candidate_count": 0,
        "executed_candidate_count": 0,
        "chain_until_satisfied": False,
        "comparison_mode": "not_available",
        "candidate_executions": [],
        "candidate_comparison": [],
        "best_candidate_execution": {},
        "best_candidate_summary": {},
        "best_terminal_candidate_summary": {},
    }


def _normalize_action_candidate_summary(
    history: Mapping[str, Any],
    fallback: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    summary = dict(history.get("best_terminal_candidate_summary") or history.get("best_candidate_summary") or {})
    if summary:
        return summary
    fallback_summary = dict(fallback or {})
    if not fallback_summary:
        return {}
    return {
        "candidate_type": str(fallback_summary.get("candidate_type") or ""),
        "candidate_action_type": str(fallback_summary.get("candidate_action_type") or ""),
        "candidate_source_type": str(fallback_summary.get("best_candidate_source_type") or ""),
        "candidate_source_id": str(fallback_summary.get("candidate_source_id") or ""),
        "candidate_support_strength": str(fallback_summary.get("candidate_support_strength") or ""),
        "executed": False,
        "auto_chained": False,
        "resolution_status": "",
        "resolved_directly": False,
        "terminal_action_type": str(fallback_summary.get("terminal_action_type") or ""),
        "terminal_source_type": str(fallback_summary.get("best_terminal_source_type") or ""),
        "terminal_source_id": str(fallback_summary.get("terminal_source_id") or ""),
        "terminal_support_strength": str(fallback_summary.get("best_terminal_support_strength") or ""),
        "terminal_result_count": int(fallback_summary.get("terminal_result_count") or 0),
        "terminal_reason": str(fallback_summary.get("terminal_reason") or ""),
        "selection_rationale": str(fallback_summary.get("selection_rationale") or ""),
        "successful_action_summary": {},
    }


def _build_successful_action_summary(
    execution: Mapping[str, Any],
    *,
    fallback_query: str,
) -> Dict[str, Any]:
    return {
        "executed": bool(execution.get("executed")),
        "action_type": str(execution.get("action_type") or ""),
        "source_type": str(execution.get("source_type") or ""),
        "source": str(execution.get("source") or ""),
        "source_id": str(
            dict(execution.get("job") or {}).get("source_id")
            or dict(execution.get("proof_packet") or {}).get("proof_id")
            or ""
        ),
        "query": str(
            dict(execution.get("job") or {}).get("retrieval_query")
            or fallback_query
            or ""
        ),
        "result_count": int(execution.get("result_count") or 0),
        "reason": str(execution.get("reason") or ""),
        "support_strength": _classify_execution_support_strength(execution),
        "evidence_preview": _build_execution_evidence_preview(execution),
    }


def _build_candidate_execution_summary(
    candidate: Mapping[str, Any],
    execution: Mapping[str, Any],
) -> Dict[str, Any]:
    successful_action = dict(execution.get("successful_action_summary") or {})
    candidate_action_type = str(candidate.get("action_type") or "")
    candidate_source_type = str(candidate.get("source_type") or "")
    candidate_source_id = str(candidate.get("source_id") or "")
    terminal_action_type = str(successful_action.get("action_type") or "")
    terminal_source_type = str(successful_action.get("source_type") or "")
    terminal_source_id = str(successful_action.get("source_id") or "")
    source_matches = (
        candidate_source_type == terminal_source_type
        and (not candidate_source_id or not terminal_source_id or candidate_source_id == terminal_source_id)
    )
    action_matches = candidate_action_type == terminal_action_type
    resolves_directly = bool(source_matches and action_matches)
    auto_chained = bool(execution.get("auto_chained"))
    if not bool(execution.get("executed")):
        resolution_status = "not_executed"
    elif resolves_directly and auto_chained:
        resolution_status = "chained_direct"
    elif resolves_directly:
        resolution_status = "direct"
    else:
        resolution_status = "redirected"
    return {
        "candidate_type": str(candidate.get("candidate_type") or ""),
        "candidate_action_type": candidate_action_type,
        "candidate_source_type": candidate_source_type,
        "candidate_source_id": candidate_source_id,
        "candidate_support_strength": str(candidate.get("support_strength") or ""),
        "auto_chained": auto_chained,
        "resolution_status": resolution_status,
        "resolved_directly": resolves_directly,
        "terminal_action_type": terminal_action_type,
        "terminal_source_type": terminal_source_type,
        "terminal_source_id": terminal_source_id,
        "terminal_support_strength": str(successful_action.get("support_strength") or ""),
        "successful_action_summary": successful_action,
    }


def _build_action_candidate_execution_row(execution: Mapping[str, Any]) -> Dict[str, Any]:
    candidate = dict(execution.get("action_candidate") or {})
    summary = dict(execution.get("candidate_execution_summary") or {})
    successful_action = dict(summary.get("successful_action_summary") or {})
    return {
        "candidate_type": str(summary.get("candidate_type") or candidate.get("candidate_type") or ""),
        "candidate_action_type": str(summary.get("candidate_action_type") or candidate.get("action_type") or ""),
        "candidate_source_type": str(summary.get("candidate_source_type") or candidate.get("source_type") or ""),
        "candidate_source_id": str(summary.get("candidate_source_id") or candidate.get("source_id") or ""),
        "candidate_support_strength": str(summary.get("candidate_support_strength") or candidate.get("support_strength") or ""),
        "executed": bool(execution.get("executed")),
        "auto_chained": bool(summary.get("auto_chained")),
        "resolution_status": str(summary.get("resolution_status") or ""),
        "resolved_directly": bool(summary.get("resolved_directly")),
        "terminal_action_type": str(summary.get("terminal_action_type") or ""),
        "terminal_source_type": str(summary.get("terminal_source_type") or ""),
        "terminal_source_id": str(summary.get("terminal_source_id") or ""),
        "terminal_support_strength": str(summary.get("terminal_support_strength") or ""),
        "terminal_result_count": int(successful_action.get("result_count") or 0),
        "terminal_reason": str(successful_action.get("reason") or execution.get("reason") or ""),
        "selection_rationale": str(candidate.get("selection_rationale") or ""),
        "successful_action_summary": successful_action,
    }


def _build_execution_evidence_preview(execution: Mapping[str, Any]) -> Dict[str, Any]:
    proof_packet = dict(execution.get("proof_packet") or {})
    proof_bundle = dict(proof_packet.get("evidence_bundle") or {})
    proof_items = [dict(item) for item in list(proof_bundle.get("evidence_items") or [])]
    if proof_items:
        item = proof_items[0]
        return {
            "kind": "proof_evidence_item",
            "id": str(item.get("evidence_id") or ""),
            "title": str(item.get("title") or ""),
            "source_type": str(item.get("source_type") or ""),
            "best_support_source": str(item.get("best_support_source") or ""),
        }
    results = [dict(item) for item in list(execution.get("results") or [])]
    if results:
        row = results[0]
        return {
            "kind": "result_row",
            "id": str(row.get("id") or row.get("document_id") or ""),
            "title": str(row.get("title") or ""),
            "source_type": str(row.get("source_type") or ""),
            "best_support_source": str(row.get("best_support_source") or ""),
        }
    return {}


def _support_strength_priority(value: Any) -> int:
    strength = str(value or "").lower()
    priorities = {
        "strong": 3,
        "moderate": 2,
        "weak": 1,
        "none": 0,
    }
    return priorities.get(strength, -1)


def _classify_execution_support_strength(execution: Mapping[str, Any]) -> str:
    if not bool(execution.get("executed")):
        return "none"
    if _follow_up_execution_satisfied(execution, top_k=max(1, int(execution.get("result_count") or 1))):
        source_type = str(execution.get("source_type") or "")
        if source_type in {"legal_dataset_parser", "proof_packet"}:
            return "strong"
        return "moderate"
    result_count = int(execution.get("result_count") or 0)
    if result_count > 0:
        return "weak"
    return "none"


def _support_strength_rank(support_strength: str) -> int:
    normalized = str(support_strength or "").lower()
    if normalized == "strong":
        return 3
    if normalized == "moderate":
        return 2
    if normalized == "weak":
        return 1
    return 0


def _proof_packet_history_summary(packet_like: Mapping[str, Any]) -> Dict[str, Any]:
    history = dict(packet_like.get("action_candidate_history") or {})
    metadata = dict(packet_like.get("metadata") or {})
    metadata_summary = dict(metadata.get("action_candidate_history_summary") or {})
    if history:
        summary = dict(
            history.get("best_terminal_candidate_summary")
            or history.get("best_candidate_summary")
            or {}
        )
        return {
            "comparison_mode": str(history.get("comparison_mode") or ""),
            "candidate_count": int(history.get("candidate_count") or 0),
            "executed_candidate_count": int(history.get("executed_candidate_count") or 0),
            "best_candidate_source_type": str(summary.get("candidate_source_type") or ""),
            "best_terminal_source_type": str(summary.get("terminal_source_type") or ""),
            "best_terminal_support_strength": str(summary.get("terminal_support_strength") or ""),
        }
    return {
        "comparison_mode": str(
            packet_like.get("comparison_mode")
            or metadata_summary.get("comparison_mode")
            or ""
        ),
        "candidate_count": int(metadata_summary.get("candidate_count") or 0),
        "executed_candidate_count": int(metadata_summary.get("executed_candidate_count") or 0),
        "best_candidate_source_type": str(
            packet_like.get("best_candidate_source_type")
            or metadata_summary.get("best_candidate_source_type")
            or ""
        ),
        "best_terminal_source_type": str(
            packet_like.get("best_terminal_source_type")
            or metadata_summary.get("best_terminal_source_type")
            or ""
        ),
        "best_terminal_support_strength": str(
            packet_like.get("best_terminal_support_strength")
            or metadata_summary.get("best_terminal_support_strength")
            or ""
        ),
    }


def _proof_packet_history_rank(packet_like: Mapping[str, Any]) -> int:
    summary = _proof_packet_history_summary(packet_like)
    rank = _support_strength_rank(str(summary.get("best_terminal_support_strength") or "")) * 10
    if str(summary.get("comparison_mode") or "") == "chain_until_satisfied":
        rank += 3
    if str(summary.get("best_terminal_source_type") or "") in {"legal_dataset_parser", "proof_packet"}:
        rank += 2
    if int(summary.get("executed_candidate_count") or 0) > 0:
        rank += 1
    return rank


def _build_proof_packet_preference_summary(packet_like: Mapping[str, Any]) -> Dict[str, Any]:
    history_summary = _proof_packet_history_summary(packet_like)
    support_strength = str(packet_like.get("support_strength") or "")
    packet_version = int(packet_like.get("packet_version") or 0)
    is_current = bool(packet_like.get("is_current", True))
    return {
        "proof_id": str(packet_like.get("proof_id") or ""),
        "is_current": is_current,
        "support_strength": support_strength,
        "packet_version": packet_version,
        "history_quality": _proof_packet_history_rank(packet_like),
        "comparison_mode": str(history_summary.get("comparison_mode") or ""),
        "best_candidate_source_type": str(history_summary.get("best_candidate_source_type") or ""),
        "best_terminal_source_type": str(history_summary.get("best_terminal_source_type") or ""),
        "best_terminal_support_strength": str(history_summary.get("best_terminal_support_strength") or ""),
        "selection_rationale": _build_proof_packet_selection_rationale(
            is_current=is_current,
            support_strength=support_strength,
            packet_version=packet_version,
            action_candidate_history_summary=history_summary,
        ),
    }


def _build_proof_packet_preference_history(
    *,
    proof_id: str,
    packet_version: int,
    current_summary: Mapping[str, Any],
    prior_packets: Sequence[Mapping[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    history: List[Dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for packet in list(prior_packets or []):
        packet_dict = dict(packet)
        existing_history = list(packet_dict.get("preference_history") or [])
        for item in existing_history:
            row = dict(item)
            key = (str(row.get("proof_id") or ""), int(row.get("packet_version") or 0))
            if not key[0] or key in seen:
                continue
            history.append(row)
            seen.add(key)
        packet_summary = dict(packet_dict.get("packet_preference_summary") or {})
        packet_proof_id = str(packet_dict.get("proof_id") or "")
        packet_packet_version = int(packet_dict.get("packet_version") or 0)
        key = (packet_proof_id, packet_packet_version)
        if packet_summary and packet_proof_id and key not in seen:
            history.append(
                {
                    "proof_id": packet_proof_id,
                    "packet_version": packet_packet_version,
                    **packet_summary,
                }
            )
            seen.add(key)
    current_row = {
        "proof_id": str(proof_id or ""),
        "packet_version": int(packet_version or 0),
        **dict(current_summary or {}),
    }
    current_key = (str(current_row.get("proof_id") or ""), int(current_row.get("packet_version") or 0))
    if current_key[0]:
        history = [item for item in history if (str(item.get("proof_id") or ""), int(item.get("packet_version") or 0)) != current_key]
        history.append(current_row)
    history.sort(key=lambda item: int(item.get("packet_version") or 0))
    return history


def _build_proof_packet_selection_rationale(
    *,
    is_current: bool,
    support_strength: str,
    packet_version: int,
    action_candidate_history_summary: Optional[Mapping[str, Any]] = None,
) -> str:
    reasons: List[str] = []
    if is_current:
        reasons.append("it is current")
    normalized_strength = str(support_strength or "").lower()
    if normalized_strength:
        reasons.append(f"it has {normalized_strength} support")
    history_summary = dict(action_candidate_history_summary or {})
    best_terminal_support_strength = str(history_summary.get("best_terminal_support_strength") or "").lower()
    comparison_mode = str(history_summary.get("comparison_mode") or "")
    best_terminal_source_type = str(history_summary.get("best_terminal_source_type") or "")
    if best_terminal_support_strength:
        history_reason = f"it has a {best_terminal_support_strength} retrieval history"
        if comparison_mode == "chain_until_satisfied":
            history_reason = f"it has a {best_terminal_support_strength} chained retrieval history"
        if best_terminal_source_type:
            history_reason += f" ending in {best_terminal_source_type}"
        reasons.append(history_reason)
    if packet_version > 0:
        reasons.append(f"it is packet version {packet_version}")
    if not reasons:
        return "Selected this proof packet because it best matched the packaged proof evidence."
    return "Selected this proof packet because " + ", ".join(reasons) + "."


def _routing_explanation_summary(packet_like: Mapping[str, Any]) -> Dict[str, Any]:
    routing = dict(packet_like.get("routing_explanation") or {})
    return {
        "routing_reason": str(routing.get("routing_reason") or ""),
        "routing_evidence": [dict(item) for item in list(routing.get("routing_evidence") or []) if isinstance(item, Mapping)],
        "preferred_corpus_keys": list(routing.get("preferred_corpus_keys") or []),
        "preferred_corpus_priority": list(routing.get("preferred_corpus_priority") or []),
        "preferred_dataset_ids": list(routing.get("preferred_dataset_ids") or []),
        "preferred_dataset_priority": list(routing.get("preferred_dataset_priority") or []),
        "preferred_state_codes": list(routing.get("preferred_state_codes") or []),
        "authority_backed": bool(routing.get("authority_backed")),
    }


def execute_packaged_docket_follow_up_plan(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
    start_step_index: int = 1,
    max_steps: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute follow-up jobs in tactician order until one produces sufficient support."""

    prepared = prepare_packaged_docket_follow_up_job(
        manifest_path,
        query,
        top_k=top_k,
        step_index=start_step_index,
    )
    if not bool(prepared.get("job_ready")):
        return {
            "query": query,
            "job_ready": False,
            "executed": False,
            "reason": str(prepared.get("reason") or "No follow-up plan is available."),
            "steps_attempted": [],
            "steps_executed": 0,
            "stopped_on_step": 0,
            "result_count": 0,
            "results": [],
            "final_execution": {},
            "available_steps": list(prepared.get("available_steps") or []),
            "execution": prepared.get("execution") or {},
            "proof_evidence_bundle": {},
        }

    available_steps = [dict(step) for step in list(prepared.get("available_steps") or [])]
    normalized_start = max(1, int(start_step_index))
    selected_steps = [step for step in available_steps if int(step.get("step_index") or 0) >= normalized_start]
    if max_steps is not None:
        selected_steps = selected_steps[: max(0, int(max_steps))]

    attempts: List[Dict[str, Any]] = []
    final_execution: Dict[str, Any] = {}
    cumulative_results: List[Dict[str, Any]] = []
    satisfied = False
    stopped_on_step = 0
    for step in selected_steps:
        prepared_step = {
            "job_ready": True,
            "source_type": str(step.get("source_type") or ""),
            "job": {
                "job_kind": "proof_retrieval_follow_up",
                "step_index": int(step.get("step_index") or 0),
                "source_id": str(step.get("source_id") or ""),
                "source_type": str(step.get("source_type") or ""),
                "label": str(step.get("label") or ""),
                "retrieval_query": str(step.get("retrieval_query") or query),
                "modules": list(step.get("modules") or []),
                "preferred_corpus_keys": list(step.get("preferred_corpus_keys") or []),
                "preferred_corpus_priority": list(step.get("preferred_corpus_priority") or []),
                "preferred_dataset_ids": list(step.get("preferred_dataset_ids") or []),
                "preferred_dataset_priority": list(step.get("preferred_dataset_priority") or []),
                "preferred_state_codes": list(step.get("preferred_state_codes") or []),
                "routing_evidence": list(step.get("routing_evidence") or []),
                "routing_reason": str(step.get("routing_reason") or ""),
                "authority_backed": bool(step.get("authority_backed")),
                "rationale": str(step.get("rationale") or ""),
                "priority": int(step.get("priority") or 0),
            },
        }
        execution = execute_packaged_docket_follow_up_job(
            manifest_path,
            prepared_step,
            top_k=top_k,
        )
        cumulative_results = _merge_follow_up_results(
            cumulative_results,
            list(execution.get("results") or []),
            source_type=str(step.get("source_type") or ""),
            step_index=int(step.get("step_index") or 0),
            top_k=top_k,
        )
        attempts.append(
            {
                "step_index": int(step.get("step_index") or 0),
                "source_type": str(step.get("source_type") or ""),
                "label": str(step.get("label") or ""),
                "result_count": int(execution.get("result_count") or 0),
                "cumulative_result_count": len(cumulative_results),
                "executed": bool(execution.get("executed")),
                "satisfied": _follow_up_execution_satisfied(execution, top_k=top_k),
                "execution": execution,
            }
        )
        final_execution = execution
        if _follow_up_execution_satisfied(execution, top_k=top_k):
            satisfied = True
            stopped_on_step = int(step.get("step_index") or 0)
            break

    if not stopped_on_step and attempts:
        stopped_on_step = int(attempts[-1].get("step_index") or 0)

    proof_evidence_bundle = build_packaged_docket_proof_evidence_bundle(
        manifest_path,
        query,
        follow_up_execution={
            "query": query,
            "job_ready": True,
            "executed": bool(attempts),
            "steps_attempted": attempts,
            "steps_executed": len(attempts),
            "stopped_on_step": int(stopped_on_step),
            "satisfied": bool(satisfied),
            "result_count": len(cumulative_results),
            "results": cumulative_results,
            "final_result_count": int(final_execution.get("result_count") or 0),
            "final_results": list(final_execution.get("results") or []),
            "final_execution": final_execution,
            "available_steps": available_steps,
            "execution": prepared.get("execution") or {},
        },
    )
    return {
        "query": query,
        "job_ready": True,
        "executed": bool(attempts),
        "reason": (
            "Stopped after follow-up support satisfied the tactician threshold."
            if satisfied
            else "Executed available follow-up steps without reaching the tactician threshold."
        ),
        "steps_attempted": attempts,
        "steps_executed": len(attempts),
        "stopped_on_step": int(stopped_on_step),
        "satisfied": bool(satisfied),
        "result_count": len(cumulative_results),
        "results": cumulative_results,
        "final_result_count": int(final_execution.get("result_count") or 0),
        "final_results": list(final_execution.get("results") or []),
        "final_execution": final_execution,
        "available_steps": available_steps,
        "execution": prepared.get("execution") or {},
        "proof_evidence_bundle": proof_evidence_bundle,
    }


def _build_reuse_current_packet_step(
    execution: Mapping[str, Any],
    *,
    query: str,
) -> Dict[str, Any]:
    for row in list(execution.get("results") or []):
        if str(row.get("source_type") or "") != "proof_packet":
            continue
        if not bool(row.get("is_current", True)):
            continue
        return {
            "step_index": 1,
            "source_id": str(row.get("proof_id") or ""),
            "source_type": "proof_packet",
            "action_type": "reuse_current_packet",
            "label": str(row.get("title") or row.get("proof_id") or "Current proof packet"),
            "priority": 0,
            "retrieval_query": str(query or ""),
            "rationale": "Reuse the current packaged proof packet before refreshing local support or escalating outward.",
            "modules": [],
        }
    return {}


def _default_follow_up_action_type(source_type: str) -> str:
    normalized = str(source_type or "")
    if normalized == "search_engine":
        return "escalate_outward"
    if normalized in {
        "authority_list",
        "local_docket_documents",
        "local_bm25_index",
        "local_vector_index",
        "legal_dataset_parser",
        "proof_packet",
    }:
        return "refresh_local_support"
    return normalized or "refresh_local_support"


def build_packaged_docket_proof_evidence_bundle(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
    follow_up_execution: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a normalized proof-evidence bundle from chained packaged follow-up retrieval."""

    execution = dict(follow_up_execution or {})
    if not execution:
        execution = execute_packaged_docket_follow_up_plan(
            manifest_path,
            query,
            top_k=top_k,
        )
    packager = DocketDatasetPackager()
    minimal_view = packager.load_minimal_dataset_view(manifest_path)
    result_rows = [dict(item) for item in list(execution.get("results") or [])]
    final_execution = dict(execution.get("final_execution") or {})
    final_job = dict(final_execution.get("job") or {})
    routing_explanation = {
        "routing_reason": str(final_job.get("routing_reason") or ""),
        "routing_evidence": [dict(item) for item in list(final_job.get("routing_evidence") or []) if isinstance(item, Mapping)],
        "preferred_corpus_keys": list(final_job.get("preferred_corpus_keys") or []),
        "preferred_corpus_priority": list(final_job.get("preferred_corpus_priority") or []),
        "preferred_dataset_ids": list(final_job.get("preferred_dataset_ids") or []),
        "preferred_dataset_priority": list(final_job.get("preferred_dataset_priority") or []),
        "preferred_state_codes": list(final_job.get("preferred_state_codes") or []),
        "authority_backed": bool(final_job.get("authority_backed")),
    }
    evidence_items = [
        _build_proof_evidence_item(row, query=query, ordinal=index)
        for index, row in enumerate(result_rows, start=1)
    ]
    retrieval_trace = [
        {
            "step_index": int(step.get("step_index") or 0),
            "source_type": str(step.get("source_type") or ""),
            "label": str(step.get("label") or ""),
            "result_count": int(step.get("result_count") or 0),
            "cumulative_result_count": int(step.get("cumulative_result_count") or 0),
            "satisfied": bool(step.get("satisfied")),
        }
        for step in list(execution.get("steps_attempted") or [])
    ]
    best_sources = [
        str(item.get("best_support_source") or "")
        for item in evidence_items
        if str(item.get("best_support_source") or "")
    ]
    unique_best_sources: List[str] = []
    for source in best_sources:
        if source not in unique_best_sources:
            unique_best_sources.append(source)
    return {
        "bundle_kind": "packaged_docket_proof_evidence",
        "query": query,
        "dataset_id": str(minimal_view.get("dataset_id") or ""),
        "docket_id": str(minimal_view.get("docket_id") or ""),
        "case_name": str(minimal_view.get("case_name") or ""),
        "court": str(minimal_view.get("court") or ""),
        "summary": {
            "evidence_item_count": len(evidence_items),
            "steps_executed": int(execution.get("steps_executed") or 0),
            "stopped_on_step": int(execution.get("stopped_on_step") or 0),
            "satisfied": bool(execution.get("satisfied")),
            "best_support_sources": unique_best_sources,
        },
        "evidence_items": evidence_items,
        "retrieval_trace": retrieval_trace,
        "final_execution": final_execution,
        "metadata": {
            "source": "execute_packaged_docket_follow_up_plan",
            "result_count": int(execution.get("result_count") or 0),
            "final_result_count": int(execution.get("final_result_count") or 0),
            "routing_explanation": routing_explanation,
        },
    }


def build_packaged_docket_proof_assistant_packet(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
    follow_up_execution: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach packaged retrieval evidence to the best matching proof-assistant work item."""

    execution = dict(follow_up_execution or {})
    if not execution:
        execution = execute_packaged_docket_follow_up_plan(
            manifest_path,
            query,
            top_k=top_k,
        )
    evidence_bundle = dict(
        execution.get("proof_evidence_bundle")
        or build_packaged_docket_proof_evidence_bundle(
            manifest_path,
            query,
            top_k=top_k,
            follow_up_execution=execution,
        )
    )
    packager = DocketDatasetPackager()
    minimal_view = packager.load_minimal_dataset_view(manifest_path)
    package_view = load_packaged_docket_dataset(manifest_path)
    existing_proof_assistant = dict(package_view.get("proof_assistant") or {})
    proof_match = _select_packaged_proof_work_item_match(
        manifest_path,
        query,
        execution=execution,
    )
    matched_work_item = dict(proof_match.get("matched_work_item") or {})
    matched_plan = dict(matched_work_item.get("plan") or {})
    work_item_id = str(matched_work_item.get("work_item_id") or "")
    existing_packets = [
        dict(item)
        for item in list(existing_proof_assistant.get("evidence_packets") or [])
        if isinstance(item, Mapping)
    ]
    work_item_packets = [
        item
        for item in existing_packets
        if str(item.get("work_item_id") or "") == work_item_id
    ]
    packet_version = 1 + max(
        [int(item.get("packet_version") or 0) for item in work_item_packets] or [0]
    )
    supersedes_proof_ids = [
        str(item.get("proof_id") or "")
        for item in work_item_packets
        if str(item.get("proof_id") or "")
        and bool(item.get("is_current", True))
    ]
    proof_id_seed = work_item_id or query
    proof_id = (
        f"{str(minimal_view.get('dataset_id') or '')}:retrieval_proof:"
        f"{_safe_identifier(proof_id_seed)}:v{packet_version}"
    )
    evidence_items = [dict(item) for item in list(evidence_bundle.get("evidence_items") or [])]
    support_summary = dict(execution.get("successful_action_summary") or {})
    support_strength = str(
        support_summary.get("support_strength")
        or _classify_execution_support_strength(dict(execution.get("final_execution") or execution))
    )
    action_candidate_history = _build_persisted_action_candidate_history(
        manifest_path,
        query,
        execution=execution,
        top_k=top_k,
    )
    best_action_candidate_summary = _normalize_action_candidate_summary(action_candidate_history)
    packet_preference_summary = _build_proof_packet_preference_summary(
        {
            "proof_id": proof_id,
            "is_current": True,
            "support_strength": support_strength,
            "packet_version": packet_version,
            "action_candidate_history": action_candidate_history,
        }
    )
    preference_history = _build_proof_packet_preference_history(
        proof_id=proof_id,
        packet_version=packet_version,
        current_summary=packet_preference_summary,
        prior_packets=work_item_packets,
    )
    preference_history_summary = _build_query_proof_preference_history_summary(
        query=query,
        result_rows=[
            {
                "source_type": "proof_packet",
                "proof_id": proof_id,
                "packet_version": packet_version,
                "preference_history": preference_history,
            }
        ],
        proof_preference_summary={
            "preferred_source_type": "proof_packet",
            "preferred_source_id": proof_id,
            "preferred_action_type": "reuse_current_packet",
        },
    )
    preference_review_trigger = _build_proof_preference_review_trigger(
        preference_history_summary,
    )
    proof_record = {
        "proof_id": proof_id,
        "work_item_id": work_item_id,
        "packet_version": packet_version,
        "is_current": True,
        "superseded": False,
        "supersedes_proof_ids": supersedes_proof_ids,
        "superseded_by_proof_id": "",
        "query": query,
        "status": "collected_evidence",
        "title": str(matched_work_item.get("title") or query),
        "party": str(matched_work_item.get("party") or ""),
        "modality": str(matched_work_item.get("modality") or ""),
        "action": str(matched_work_item.get("action") or ""),
        "source_type": str(matched_work_item.get("source_type") or ""),
        "authority_ids": list(matched_work_item.get("authority_ids") or []),
        "evidence_bundle": evidence_bundle,
        "evidence_ids": [str(item.get("evidence_id") or "") for item in evidence_items if str(item.get("evidence_id") or "")],
        "support_strength": support_strength,
        "matched_plan": matched_plan,
        "retrieval_trace": list(evidence_bundle.get("retrieval_trace") or []),
        "action_candidate_history": action_candidate_history,
        "packet_preference_summary": packet_preference_summary,
        "preference_history": preference_history,
        "preference_history_summary": preference_history_summary,
        "preference_review_trigger": preference_review_trigger,
        "routing_explanation": dict((evidence_bundle.get("metadata") or {}).get("routing_explanation") or {}),
        "certificates": [],
        "metadata": {
            "backend": "packaged_docket_follow_up_proof_packet",
            "zkp_status": "not_implemented",
            "matched_query": str(proof_match.get("matched_query") or ""),
            "matched_score": float(proof_match.get("matched_score") or 0.0),
            "dataset_id": str(minimal_view.get("dataset_id") or ""),
            "docket_id": str(minimal_view.get("docket_id") or ""),
            "support_strength": support_strength,
            "action_candidate_history_summary": {
                "comparison_mode": str(action_candidate_history.get("comparison_mode") or ""),
                "candidate_count": int(action_candidate_history.get("candidate_count") or 0),
                "executed_candidate_count": int(action_candidate_history.get("executed_candidate_count") or 0),
                "best_candidate_source_type": str(best_action_candidate_summary.get("candidate_source_type") or ""),
                "best_terminal_source_type": str(best_action_candidate_summary.get("terminal_source_type") or ""),
                "best_terminal_support_strength": str(best_action_candidate_summary.get("terminal_support_strength") or ""),
            },
            "packet_preference_summary": packet_preference_summary,
            "preference_history_count": len(preference_history),
            "preference_review_trigger": preference_review_trigger,
            "proof_lineage": {
                "packet_version": packet_version,
                "is_current": True,
                "superseded": False,
                "supersedes_proof_ids": supersedes_proof_ids,
                "superseded_by_proof_id": "",
            },
            "routing_explanation": dict((evidence_bundle.get("metadata") or {}).get("routing_explanation") or {}),
        },
    }
    proof_store = {
        "proofs": {proof_id: proof_record},
        "certificates": [],
        "summary": {
            "proof_count": 1,
            "evidence_item_count": len(evidence_items),
            "matched_work_item_count": 1 if work_item_id else 0,
        },
        "metadata": {
            "backend": "packaged_docket_follow_up_proof_packet",
            "zkp_status": "not_implemented",
        },
    }
    return {
        "packet_kind": "packaged_docket_proof_assistant_packet",
        "query": query,
        "dataset_id": str(minimal_view.get("dataset_id") or ""),
        "docket_id": str(minimal_view.get("docket_id") or ""),
        "proof_id": proof_id,
        "packet_version": packet_version,
        "is_current": True,
        "superseded": False,
        "supersedes_proof_ids": supersedes_proof_ids,
        "superseded_by_proof_id": "",
        "support_strength": support_strength,
        "action_candidate_history": action_candidate_history,
        "best_action_candidate_summary": best_action_candidate_summary,
        "packet_preference_summary": packet_preference_summary,
        "preference_history": preference_history,
        "preference_history_summary": preference_history_summary,
        "preference_review_trigger": preference_review_trigger,
        "matched_work_item": matched_work_item,
        "matched_plan": matched_plan,
        "evidence_bundle": evidence_bundle,
        "routing_explanation": dict((evidence_bundle.get("metadata") or {}).get("routing_explanation") or {}),
        "proof_store": proof_store,
    }


def attach_packaged_docket_proof_assistant_packet(
    manifest_path: str | Path,
    query: str,
    *,
    top_k: int = 10,
    follow_up_execution: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Load a packaged docket dataset view and attach a proof-assistant packet to it."""

    package_view = load_packaged_docket_dataset(manifest_path)
    packet = build_packaged_docket_proof_assistant_packet(
        manifest_path,
        query,
        top_k=top_k,
        follow_up_execution=follow_up_execution,
    )
    return _attach_packet_to_package_view(package_view, packet, query=query)


def enrich_packaged_docket_with_tactician(
    manifest_path: str | Path,
    queries: Sequence[str],
    *,
    top_k: int = 10,
) -> Dict[str, Any]:
    """Apply one or more tactician-guided proof-packet enrichments to a packaged docket view."""

    package_view = load_packaged_docket_dataset(manifest_path)
    normalized_queries = [str(query).strip() for query in list(queries or []) if str(query).strip()]
    enrichments: List[Dict[str, Any]] = []
    for query in normalized_queries:
        execution = execute_packaged_docket_follow_up_plan(
            manifest_path,
            query,
            top_k=top_k,
        )
        packet = build_packaged_docket_proof_assistant_packet(
            manifest_path,
            query,
            top_k=top_k,
            follow_up_execution=execution,
        )
        package_view = _attach_packet_to_package_view(
            package_view,
            packet,
            query=query,
        )
        refresh = dict(package_view.get("proof_packet_refresh") or {})
        enrichments.append(
            {
                "query": query,
                "proof_id": str((package_view.get("attached_proof_assistant_packet") or {}).get("proof_id") or ""),
                "packet_version": int((package_view.get("attached_proof_assistant_packet") or {}).get("packet_version") or 0),
                "support_strength": str((package_view.get("attached_proof_assistant_packet") or {}).get("support_strength") or ""),
                "decision": str(refresh.get("decision") or ""),
                "material_change_detected": bool(refresh.get("material_change_detected")),
                "result_count": int((dict(execution.get("proof_evidence_bundle") or {}).get("summary") or {}).get("evidence_item_count") or 0),
            }
        )
    metadata = dict(package_view.get("metadata") or {})
    metadata["tactician_enriched"] = bool(enrichments)
    metadata["tactician_enrichment_query_count"] = len(enrichments)
    metadata["tactician_enrichment_queries"] = normalized_queries
    package_view["metadata"] = metadata
    package_view["tactician_enrichments"] = enrichments
    return package_view


def _attach_packet_to_package_view(
    package_view: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    query: str,
) -> Dict[str, Any]:
    package_view = dict(package_view)
    packet = _rebase_packet_version_against_view(
        dict(packet),
        dict(package_view.get("proof_assistant") or {}),
        query=query,
    )
    proof_assistant = dict(package_view.get("proof_assistant") or {})
    matched_work_item = dict(packet.get("matched_work_item") or {})
    matched_work_item_id = str(matched_work_item.get("work_item_id") or "")
    current_packet_summary = _find_current_proof_packet_summary(
        proof_assistant,
        work_item_id=matched_work_item_id,
    )
    current_proof_payload = _find_proof_store_entry(
        proof_assistant,
        proof_id=str(current_packet_summary.get("proof_id") or ""),
    )
    def _apply_agenda_packet_metadata(
        agenda_rows: Sequence[Mapping[str, Any]],
        packet_like: Mapping[str, Any],
    ) -> Tuple[List[Dict[str, Any]], int]:
        review_metadata = _build_agenda_revalidation_metadata(
            packet_like.get("preference_review_trigger") or {},
        )
        updated_agenda = [dict(item) for item in list(agenda_rows or [])]
        updated_count = 0
        for item in updated_agenda:
            if str(item.get("work_item_id") or "") != matched_work_item_id:
                continue
            evidence_packet_ids = [
                str(value)
                for value in list(item.get("evidence_packet_ids") or [])
                if str(value).strip()
            ]
            if str(packet_like.get("proof_id") or "") and str(packet_like.get("proof_id") or "") not in evidence_packet_ids:
                evidence_packet_ids.append(str(packet_like.get("proof_id") or ""))
            item["evidence_packet_ids"] = evidence_packet_ids
            item["attached_evidence_count"] = len(
                list((packet_like.get("evidence_bundle") or {}).get("evidence_items") or [])
            )
            item["latest_proof_packet_id"] = str(packet_like.get("proof_id") or "")
            item["current_proof_packet_id"] = str(packet_like.get("proof_id") or "")
            item["current_proof_packet_version"] = int(packet_like.get("packet_version") or 0)
            item["current_proof_packet_support_strength"] = str(packet_like.get("support_strength") or "")
            item.update(review_metadata)
            item["evidence_status"] = "collected_evidence"
            updated_count += 1
        return updated_agenda, updated_count

    if current_packet_summary and current_proof_payload and not _proof_packet_material_change(
        current_proof_payload,
        packet,
    ):
        reused_packet = _build_existing_proof_assistant_packet(
            current_proof_payload,
            current_packet_summary,
            packet,
        )
        routing_summary = _routing_explanation_summary(reused_packet)
        agenda, attached_work_item_count = _apply_agenda_packet_metadata(
            proof_assistant.get("agenda") or [],
            reused_packet,
        )
        package_metadata = dict(package_view.get("metadata") or {})
        package_metadata["proof_packet_attached"] = True
        package_metadata["latest_proof_packet_id"] = str(reused_packet.get("proof_id") or "")
        package_metadata["latest_proof_packet_version"] = int(reused_packet.get("packet_version") or 0)
        package_metadata["proof_packet_reused"] = True
        package_metadata["latest_proof_packet_routing_explanation"] = routing_summary
        package_view["metadata"] = package_metadata
        agenda = _sort_proof_agenda_items(agenda)
        revalidation_counts = _count_agenda_revalidation_items(agenda)
        proof_metadata = dict(proof_assistant.get("metadata") or {})
        proof_metadata["latest_proof_packet_id"] = str(reused_packet.get("proof_id") or "")
        proof_metadata["latest_proof_packet_version"] = int(reused_packet.get("packet_version") or 0)
        proof_metadata["latest_proof_packet_query"] = query
        proof_metadata["proof_packet_reused"] = True
        proof_metadata["latest_proof_packet_routing_explanation"] = routing_summary
        proof_metadata["latest_proof_packet_support_strength"] = str(reused_packet.get("support_strength") or "")
        proof_metadata["latest_proof_packet_preference_history_count"] = len(list(reused_packet.get("preference_history") or []))
        proof_metadata["latest_proof_packet_review_trigger"] = dict(reused_packet.get("preference_review_trigger") or {})
        summary = dict(proof_assistant.get("summary") or {})
        summary["attached_work_item_count"] = attached_work_item_count
        summary["latest_proof_packet_support_strength"] = str(reused_packet.get("support_strength") or "")
        summary["latest_proof_packet_preference_history_count"] = len(list(reused_packet.get("preference_history") or []))
        summary["latest_proof_packet_review_required"] = bool(
            (reused_packet.get("preference_review_trigger") or {}).get("review_required")
        )
        summary.update(revalidation_counts)
        proof_assistant["summary"] = summary
        proof_assistant["agenda"] = agenda
        proof_assistant["metadata"] = proof_metadata
        package_view["proof_assistant"] = proof_assistant
        package_view["attached_proof_assistant_packet"] = reused_packet
        package_view["proof_packet_refresh"] = {
            "decision": "reused_current_packet",
            "material_change_detected": False,
            "proof_id": str(reused_packet.get("proof_id") or ""),
            "packet_version": int(reused_packet.get("packet_version") or 0),
            "routing_explanation": routing_summary,
        }
        return package_view

    agenda, attached_work_item_count = _apply_agenda_packet_metadata(
        proof_assistant.get("agenda") or [],
        packet,
    )

    agenda = _sort_proof_agenda_items(agenda)
    revalidation_counts = _count_agenda_revalidation_items(agenda)
    existing_packets = [dict(item) for item in list(proof_assistant.get("evidence_packets") or [])]
    existing_packet_ids = {str(item.get("proof_id") or "") for item in existing_packets if str(item.get("proof_id") or "")}
    superseded_packet_ids: List[str] = []
    for existing_packet in existing_packets:
        if str(existing_packet.get("work_item_id") or "") != matched_work_item_id:
            continue
        if not bool(existing_packet.get("is_current", True)):
            continue
        existing_proof_id = str(existing_packet.get("proof_id") or "")
        if not existing_proof_id or existing_proof_id == str(packet.get("proof_id") or ""):
            continue
        existing_packet["is_current"] = False
        existing_packet["superseded"] = True
        existing_packet["superseded_by_proof_id"] = str(packet.get("proof_id") or "")
        superseded_packet_ids.append(existing_proof_id)
    packet_summary = {
        "proof_id": str(packet.get("proof_id") or ""),
        "query": query,
        "work_item_id": matched_work_item_id,
        "bundle_kind": str(((packet.get("evidence_bundle") or {}).get("bundle_kind")) or ""),
        "evidence_item_count": len(list(((packet.get("evidence_bundle") or {}).get("evidence_items") or []))),
        "matched_plan_id": str(((packet.get("matched_plan") or {}).get("plan_id")) or ""),
        "packet_version": int(packet.get("packet_version") or 0),
        "is_current": True,
        "superseded": False,
        "supersedes_proof_ids": superseded_packet_ids,
        "superseded_by_proof_id": "",
        "support_strength": str(packet.get("support_strength") or ""),
        "comparison_mode": str(((packet.get("action_candidate_history") or {}).get("comparison_mode")) or ""),
        "best_candidate_source_type": str(((packet.get("best_action_candidate_summary") or {}).get("candidate_source_type")) or ""),
        "best_terminal_source_type": str(((packet.get("best_action_candidate_summary") or {}).get("terminal_source_type")) or ""),
        "best_terminal_support_strength": str(((packet.get("best_action_candidate_summary") or {}).get("terminal_support_strength")) or ""),
        "packet_preference_summary": dict(packet.get("packet_preference_summary") or {}),
        "preference_history": list(packet.get("preference_history") or []),
        "preference_review_trigger": dict(packet.get("preference_review_trigger") or {}),
    }
    if str(packet_summary.get("proof_id") or "") and str(packet_summary.get("proof_id") or "") not in existing_packet_ids:
        existing_packets.append(packet_summary)

    proof_store = dict(proof_assistant.get("proof_store") or {})
    merged_proofs = dict(proof_store.get("proofs") or {})
    for superseded_proof_id in superseded_packet_ids:
        existing_proof = dict(merged_proofs.get(superseded_proof_id) or {})
        if not existing_proof:
            continue
        existing_proof["is_current"] = False
        existing_proof["superseded"] = True
        existing_proof["superseded_by_proof_id"] = str(packet.get("proof_id") or "")
        existing_proof_metadata = dict(existing_proof.get("metadata") or {})
        proof_lineage = dict(existing_proof_metadata.get("proof_lineage") or {})
        proof_lineage["is_current"] = False
        proof_lineage["superseded"] = True
        proof_lineage["superseded_by_proof_id"] = str(packet.get("proof_id") or "")
        existing_proof_metadata["proof_lineage"] = proof_lineage
        existing_proof["metadata"] = existing_proof_metadata
        merged_proofs[superseded_proof_id] = existing_proof
    merged_proofs.update(dict((packet.get("proof_store") or {}).get("proofs") or {}))
    merged_certificates = list(proof_store.get("certificates") or [])
    merged_certificates.extend(list((packet.get("proof_store") or {}).get("certificates") or []))
    current_packet_count = sum(1 for item in existing_packets if bool(item.get("is_current", True)))
    superseded_packet_count = sum(1 for item in existing_packets if bool(item.get("superseded")))
    proof_assistant["proof_store"] = {
        "proofs": merged_proofs,
        "certificates": merged_certificates,
        "summary": {
            "proof_count": len(merged_proofs),
            "evidence_item_count": sum(
                len(list((proof.get("evidence_bundle") or {}).get("evidence_items") or []))
                for proof in merged_proofs.values()
                if isinstance(proof, Mapping)
            ),
            "packet_count": len(existing_packets),
            "current_packet_count": current_packet_count,
            "superseded_packet_count": superseded_packet_count,
        },
        "metadata": {
            "backend": "packaged_docket_follow_up_proof_packet",
            "zkp_status": "not_implemented",
        },
    }
    summary = dict(proof_assistant.get("summary") or {})
    summary["proof_packet_count"] = len(existing_packets)
    summary["proof_count"] = len(merged_proofs)
    summary["evidence_item_count"] = int((proof_assistant.get("proof_store") or {}).get("summary", {}).get("evidence_item_count") or 0)
    summary["attached_work_item_count"] = attached_work_item_count
    summary["current_proof_packet_count"] = current_packet_count
    summary["superseded_proof_packet_count"] = superseded_packet_count
    summary["latest_proof_packet_support_strength"] = str(packet.get("support_strength") or "")
    summary["latest_proof_packet_comparison_mode"] = str(((packet.get("action_candidate_history") or {}).get("comparison_mode")) or "")
    summary["latest_proof_packet_best_terminal_source_type"] = str(((packet.get("best_action_candidate_summary") or {}).get("terminal_source_type")) or "")
    summary["latest_proof_packet_best_terminal_support_strength"] = str(((packet.get("best_action_candidate_summary") or {}).get("terminal_support_strength")) or "")
    summary["latest_proof_packet_preference_history_count"] = len(list(packet.get("preference_history") or []))
    summary["latest_proof_packet_review_required"] = bool((packet.get("preference_review_trigger") or {}).get("review_required"))
    summary.update(revalidation_counts)
    proof_assistant["summary"] = summary
    proof_assistant["agenda"] = agenda
    proof_assistant["evidence_packets"] = existing_packets
    metadata = dict(proof_assistant.get("metadata") or {})
    metadata["latest_proof_packet_id"] = str(packet.get("proof_id") or "")
    metadata["latest_proof_packet_query"] = query
    metadata["latest_proof_packet_version"] = int(packet.get("packet_version") or 0)
    metadata["latest_proof_packet_support_strength"] = str(packet.get("support_strength") or "")
    metadata["latest_proof_packet_comparison_mode"] = str(((packet.get("action_candidate_history") or {}).get("comparison_mode")) or "")
    metadata["latest_proof_packet_best_terminal_source_type"] = str(((packet.get("best_action_candidate_summary") or {}).get("terminal_source_type")) or "")
    metadata["latest_proof_packet_best_terminal_support_strength"] = str(((packet.get("best_action_candidate_summary") or {}).get("terminal_support_strength")) or "")
    metadata["latest_proof_packet_preference_history_count"] = len(list(packet.get("preference_history") or []))
    metadata["latest_proof_packet_review_trigger"] = dict(packet.get("preference_review_trigger") or {})
    metadata["current_proof_packet_count"] = current_packet_count
    metadata["superseded_proof_packet_count"] = superseded_packet_count
    proof_assistant["metadata"] = metadata

    package_view["proof_assistant"] = proof_assistant
    routing_summary = _routing_explanation_summary(packet)
    package_metadata = dict(package_view.get("metadata") or {})
    package_metadata["proof_packet_attached"] = True
    package_metadata["latest_proof_packet_id"] = str(packet.get("proof_id") or "")
    package_metadata["latest_proof_packet_version"] = int(packet.get("packet_version") or 0)
    package_metadata["proof_packet_reused"] = False
    package_metadata["latest_proof_packet_routing_explanation"] = routing_summary
    package_view["metadata"] = package_metadata
    package_view["attached_proof_assistant_packet"] = packet
    package_view["proof_packet_refresh"] = {
        "decision": "created_new_packet",
        "material_change_detected": True,
        "proof_id": str(packet.get("proof_id") or ""),
        "packet_version": int(packet.get("packet_version") or 0),
        "routing_explanation": routing_summary,
    }
    return package_view


def _find_current_proof_packet_summary(
    proof_assistant: Mapping[str, Any],
    *,
    work_item_id: str,
) -> Dict[str, Any]:
    for packet in list(proof_assistant.get("evidence_packets") or []):
        if not isinstance(packet, Mapping):
            continue
        if str(packet.get("work_item_id") or "") != str(work_item_id or ""):
            continue
        if not bool(packet.get("is_current", True)):
            continue
        return dict(packet)
    return {}


def _find_proof_store_entry(
    proof_assistant: Mapping[str, Any],
    *,
    proof_id: str,
) -> Dict[str, Any]:
    proofs = dict((dict(proof_assistant.get("proof_store") or {})).get("proofs") or {})
    return dict(proofs.get(str(proof_id or "")) or {})


def _proof_packet_support_signature(packet_like: Mapping[str, Any]) -> Dict[str, Any]:
    evidence_bundle = dict(packet_like.get("evidence_bundle") or {})
    evidence_items = [dict(item) for item in list(evidence_bundle.get("evidence_items") or [])]
    matched_work_item = dict(packet_like.get("matched_work_item") or {})
    matched_plan = dict(packet_like.get("matched_plan") or {})
    best_support_sources: List[str] = []
    for item in evidence_items:
        source = str(item.get("best_support_source") or "")
        if source and source not in best_support_sources:
            best_support_sources.append(source)
    retrieval_trace = [
        {
            "source_type": str(step.get("source_type") or ""),
            "satisfied": bool(step.get("satisfied")),
        }
        for step in list(evidence_bundle.get("retrieval_trace") or packet_like.get("retrieval_trace") or [])
        if isinstance(step, Mapping)
    ]
    return {
        "work_item_id": str(packet_like.get("work_item_id") or matched_work_item.get("work_item_id") or ""),
        "matched_plan_id": str(matched_plan.get("plan_id") or matched_work_item.get("plan_id") or ""),
        "evidence_ids": sorted(
            str(item.get("evidence_id") or "")
            for item in evidence_items
            if str(item.get("evidence_id") or "")
        ),
        "evidence_item_count": len(evidence_items),
        "best_support_sources": best_support_sources,
        "retrieval_trace": retrieval_trace,
        "satisfied": bool((dict(evidence_bundle.get("summary") or {})).get("satisfied")),
    }


def _proof_packet_material_change(
    existing_packet: Mapping[str, Any],
    new_packet: Mapping[str, Any],
) -> bool:
    return _proof_packet_support_signature(existing_packet) != _proof_packet_support_signature(new_packet)


def _build_existing_proof_assistant_packet(
    existing_proof_payload: Mapping[str, Any],
    current_packet_summary: Mapping[str, Any],
    new_packet: Mapping[str, Any],
) -> Dict[str, Any]:
    proof_id = str(existing_proof_payload.get("proof_id") or current_packet_summary.get("proof_id") or "")
    existing_store = {
        "proofs": {proof_id: dict(existing_proof_payload)},
        "certificates": list(existing_proof_payload.get("certificates") or []),
        "summary": {
            "proof_count": 1,
            "evidence_item_count": len(list((dict(existing_proof_payload.get("evidence_bundle") or {})).get("evidence_items") or [])),
            "matched_work_item_count": 1 if str(existing_proof_payload.get("work_item_id") or "") else 0,
        },
        "metadata": {
            "backend": "packaged_docket_follow_up_proof_packet",
            "zkp_status": "not_implemented",
        },
    }
    reused_packet = {
        "packet_kind": "packaged_docket_proof_assistant_packet",
        "query": str(new_packet.get("query") or existing_proof_payload.get("query") or ""),
        "dataset_id": str(new_packet.get("dataset_id") or ""),
        "docket_id": str(new_packet.get("docket_id") or ""),
        "proof_id": proof_id,
        "packet_version": int(existing_proof_payload.get("packet_version") or current_packet_summary.get("packet_version") or 0),
        "is_current": bool(existing_proof_payload.get("is_current", current_packet_summary.get("is_current", True))),
        "superseded": bool(existing_proof_payload.get("superseded", current_packet_summary.get("superseded", False))),
        "supersedes_proof_ids": list(existing_proof_payload.get("supersedes_proof_ids") or current_packet_summary.get("supersedes_proof_ids") or []),
        "superseded_by_proof_id": str(
            existing_proof_payload.get("superseded_by_proof_id") or current_packet_summary.get("superseded_by_proof_id") or ""
        ),
        "support_strength": str(existing_proof_payload.get("support_strength") or current_packet_summary.get("support_strength") or ""),
        "action_candidate_history": dict(
            existing_proof_payload.get("action_candidate_history")
            or new_packet.get("action_candidate_history")
            or {}
        ),
        "best_action_candidate_summary": _normalize_action_candidate_summary(
            dict(existing_proof_payload.get("action_candidate_history") or new_packet.get("action_candidate_history") or {}),
            fallback=(dict(existing_proof_payload.get("metadata") or {})).get("action_candidate_history_summary"),
        ),
        "matched_work_item": dict(new_packet.get("matched_work_item") or {}),
        "matched_plan": dict(existing_proof_payload.get("matched_plan") or new_packet.get("matched_plan") or {}),
        "evidence_bundle": dict(existing_proof_payload.get("evidence_bundle") or {}),
        "proof_store": existing_store,
        "refresh_decision": "reused_current_packet",
        "material_change_detected": False,
    }
    reused_packet["packet_preference_summary"] = _build_proof_packet_preference_summary(
        {
            "proof_id": proof_id,
            "is_current": bool(reused_packet.get("is_current", True)),
            "support_strength": str(reused_packet.get("support_strength") or ""),
            "packet_version": int(reused_packet.get("packet_version") or 0),
            "action_candidate_history": reused_packet.get("action_candidate_history"),
            "metadata": existing_proof_payload.get("metadata"),
        }
    )
    reused_packet["preference_history"] = list(
        existing_proof_payload.get("preference_history")
        or current_packet_summary.get("preference_history")
        or _build_proof_packet_preference_history(
            proof_id=proof_id,
            packet_version=int(reused_packet.get("packet_version") or 0),
            current_summary=dict(reused_packet.get("packet_preference_summary") or {}),
            prior_packets=[],
        )
    )
    reused_packet["preference_history_summary"] = _build_query_proof_preference_history_summary(
        query=str(reused_packet.get("query") or ""),
        result_rows=[
            {
                "source_type": "proof_packet",
                "proof_id": proof_id,
                "packet_version": int(reused_packet.get("packet_version") or 0),
                "preference_history": list(reused_packet.get("preference_history") or []),
            }
        ],
        proof_preference_summary={
            "preferred_source_type": "proof_packet",
            "preferred_source_id": proof_id,
            "preferred_action_type": "reuse_current_packet",
        },
    )
    reused_packet["preference_review_trigger"] = _build_proof_preference_review_trigger(
        reused_packet["preference_history_summary"],
    )
    return reused_packet


def _rebase_packet_version_against_view(
    packet: Dict[str, Any],
    proof_assistant: Mapping[str, Any],
    *,
    query: str,
) -> Dict[str, Any]:
    matched_work_item = dict(packet.get("matched_work_item") or {})
    work_item_id = str(packet.get("work_item_id") or matched_work_item.get("work_item_id") or "")
    if not work_item_id:
        return packet
    existing_packets = [
        dict(item)
        for item in list(proof_assistant.get("evidence_packets") or [])
        if isinstance(item, Mapping) and str(item.get("work_item_id") or "") == work_item_id
    ]
    if not existing_packets:
        return packet

    current_packet_summary = _find_current_proof_packet_summary(proof_assistant, work_item_id=work_item_id)
    current_proof_payload = _find_proof_store_entry(
        proof_assistant,
        proof_id=str(current_packet_summary.get("proof_id") or ""),
    )
    if current_packet_summary and current_proof_payload and not _proof_packet_material_change(current_proof_payload, packet):
        return _build_existing_proof_assistant_packet(current_proof_payload, current_packet_summary, packet)

    highest_version = max(int(item.get("packet_version") or 0) for item in existing_packets)
    packet_version = max(int(packet.get("packet_version") or 0), highest_version + 1)
    dataset_id = str(packet.get("dataset_id") or "")
    proof_id = f"{dataset_id}:retrieval_proof:{_safe_identifier(work_item_id)}:v{packet_version}"
    supersedes = [
        str(item.get("proof_id") or "")
        for item in existing_packets
        if bool(item.get("is_current", True)) and str(item.get("proof_id") or "")
    ]
    packet["query"] = str(query or packet.get("query") or "")
    packet["proof_id"] = proof_id
    packet["packet_version"] = packet_version
    packet["is_current"] = True
    packet["superseded"] = False
    packet["supersedes_proof_ids"] = supersedes
    packet["superseded_by_proof_id"] = ""

    proof_store = dict(packet.get("proof_store") or {})
    proofs = dict(proof_store.get("proofs") or {})
    old_keys = list(proofs.keys())
    if old_keys:
        payload = dict(proofs.get(old_keys[0]) or {})
        payload["proof_id"] = proof_id
        payload["packet_version"] = packet_version
        payload["is_current"] = True
        payload["superseded"] = False
        payload["supersedes_proof_ids"] = supersedes
        payload["superseded_by_proof_id"] = ""
        payload["query"] = str(query or payload.get("query") or "")
        payload["metadata"] = dict(payload.get("metadata") or {})
        lineage = dict(payload["metadata"].get("proof_lineage") or {})
        lineage["packet_version"] = packet_version
        lineage["is_current"] = True
        lineage["superseded"] = False
        lineage["supersedes_proof_ids"] = supersedes
        lineage["superseded_by_proof_id"] = ""
        payload["metadata"]["proof_lineage"] = lineage
        proof_store["proofs"] = {proof_id: payload}
    packet["proof_store"] = proof_store
    return packet


def _search_packaged_follow_up_rows(
    rows: Sequence[Mapping[str, Any]],
    query: str,
    *,
    top_k: int,
) -> List[Dict[str, Any]]:
    query_terms = {term for term in str(query or "").lower().split() if term}
    scored: List[Dict[str, Any]] = []
    for row in rows:
        title = str(row.get("title") or "")
        text = str(row.get("text") or "")
        combined = f"{title} {text}".lower()
        overlap = sum(1 for term in query_terms if term in combined)
        if overlap <= 0:
            continue
        scored.append(
            {
                "id": row.get("id") or row.get("document_id"),
                "title": title,
                "text": text,
                "score": overlap / max(1, len(query_terms)),
                "source_type": str(row.get("source_type") or ""),
            }
        )
    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return scored[:top_k]


def _build_proof_evidence_item(
    row: Mapping[str, Any],
    *,
    query: str,
    ordinal: int,
) -> Dict[str, Any]:
    evidence_id = str(
        row.get("id")
        or row.get("document_id")
        or row.get("work_item_id")
        or row.get("chunk_id")
        or f"evidence_{ordinal}"
    )
    title = str(row.get("title") or row.get("label") or evidence_id)
    text = str(row.get("text") or row.get("content") or "")
    best_support_source = str(row.get("best_support_source") or row.get("source_type") or "")
    return {
        "evidence_id": evidence_id,
        "title": title,
        "text": text,
        "score": float(row.get("score") or 0.0),
        "best_support_source": best_support_source,
        "supporting_sources": [str(item) for item in list(row.get("supporting_sources") or []) if str(item).strip()],
        "supporting_steps": [int(item) for item in list(row.get("supporting_steps") or []) if str(item).strip()],
        "source_type": str(row.get("source_type") or best_support_source),
        "query": query,
        "excerpt": text[:280],
    }


def _select_packaged_proof_work_item_match(
    manifest_path: str | Path,
    query: str,
    *,
    execution: Mapping[str, Any],
) -> Dict[str, Any]:
    adapter = PackagedDocketQueryAdapter(manifest_path)
    candidate_queries: List[str] = [str(query or "")]
    for step in list(execution.get("steps_attempted") or []):
        execution_payload = dict(step.get("execution") or {})
        job = dict(execution_payload.get("job") or {})
        retrieval_query = str(job.get("retrieval_query") or "").strip()
        if retrieval_query and retrieval_query not in candidate_queries:
            candidate_queries.append(retrieval_query)

    best_match: Dict[str, Any] = {
        "matched_query": "",
        "matched_score": 0.0,
        "matched_work_item": {},
    }
    for candidate_query in candidate_queries:
        result = adapter.search_proof_tasks(candidate_query, top_k=3)
        for item in list(result.get("results") or []):
            score = float(item.get("score") or 0.0)
            if score > float(best_match.get("matched_score") or 0.0):
                best_match = {
                    "matched_query": candidate_query,
                    "matched_score": score,
                    "matched_work_item": dict(item),
                }
    return best_match


def _follow_up_execution_satisfied(
    execution: Mapping[str, Any],
    *,
    top_k: int,
) -> bool:
    if not bool(execution.get("executed")):
        return False
    result_count = int(execution.get("result_count") or 0)
    if result_count <= 0:
        return False
    source_type = str(execution.get("source_type") or "")
    if source_type == "authority_list":
        top_score = 0.0
        top_results = list(execution.get("results") or [])
        if top_results:
            top_score = float(top_results[0].get("score") or 0.0)
        return result_count >= 2 or top_score >= 0.5
    if source_type == "proof_packet":
        proof_packet = dict(execution.get("proof_packet") or {})
        evidence_bundle = dict(proof_packet.get("evidence_bundle") or {})
        return int(dict(evidence_bundle.get("summary") or {}).get("evidence_item_count") or 0) >= 1
    if source_type == "legal_dataset_parser":
        parser_result = dict(execution.get("parser_result") or {})
        if str(parser_result.get("status") or "").lower() == "success":
            return result_count >= 1
    return result_count >= min(max(1, top_k), 1)


def _merge_follow_up_results(
    current_results: Sequence[Mapping[str, Any]],
    incoming_results: Sequence[Mapping[str, Any]],
    *,
    source_type: str,
    step_index: int,
    top_k: int,
) -> List[Dict[str, Any]]:
    source_priority = [
        "legal_dataset_parser",
        "authority_list",
        "local_docket_documents",
        "local_bm25_index",
        "local_vector_index",
        "search_engine",
    ]
    merged_index: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for candidate in list(current_results) + list(incoming_results):
        row = dict(candidate)
        identity = _follow_up_result_identity(row)
        if identity not in merged_index:
            merged_row = dict(row)
            merged_row.setdefault("supporting_sources", [source_type] if source_type else [])
            merged_row.setdefault("supporting_steps", [step_index] if step_index else [])
            merged_row["best_support_source"] = _best_follow_up_support_source(
                merged_row.get("supporting_sources"),
                source_priority=source_priority,
            )
            merged_index[identity] = merged_row
            order.append(identity)
            continue
        existing = dict(merged_index[identity])
        merged_row = dict(existing)
        merged_row.update(row)
        if float(existing.get("score") or 0.0) > float(row.get("score") or 0.0):
            merged_row["score"] = existing.get("score")
        sources = list(existing.get("supporting_sources") or [])
        if source_type and source_type not in sources:
            sources.append(source_type)
        merged_row["supporting_sources"] = sources
        steps = [int(item) for item in list(existing.get("supporting_steps") or []) if str(item).strip()]
        if step_index and step_index not in steps:
            steps.append(step_index)
        merged_row["supporting_steps"] = steps
        merged_row["best_support_source"] = _best_follow_up_support_source(
            merged_row.get("supporting_sources"),
            source_priority=source_priority,
        )
        merged_index[identity] = merged_row
    merged_rows = [merged_index[item_id] for item_id in order]
    merged_rows.sort(
        key=lambda item: _follow_up_result_rank_key(item, source_priority=source_priority),
        reverse=True,
    )
    return merged_rows[:top_k]


def _follow_up_result_identity(row: Mapping[str, Any]) -> str:
    for field in ("id", "document_id", "work_item_id", "chunk_id", "title"):
        value = row.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    return json.dumps(_jsonable(dict(row)), sort_keys=True)


def _best_follow_up_support_source(
    sources: Any,
    *,
    source_priority: Sequence[str],
) -> str:
    available = [str(item) for item in list(sources or []) if str(item).strip()]
    if not available:
        return ""
    for source_type in source_priority:
        if source_type in available:
            return source_type
    return available[0]


def _follow_up_result_rank_key(
    row: Mapping[str, Any],
    *,
    source_priority: Sequence[str],
) -> tuple[Any, ...]:
    available = [str(item) for item in list(row.get("supporting_sources") or []) if str(item).strip()]
    best_source = str(row.get("best_support_source") or "")
    source_rank = 0
    if best_source in source_priority:
        source_rank = len(source_priority) - source_priority.index(best_source)
    elif available:
        source_rank = 1
    return (
        source_rank,
        len(available),
        float(row.get("score") or 0.0),
    )


def _prepare_legal_dataset_parser_adapter(
    job: Mapping[str, Any],
    retrieval_query: str,
    *,
    top_k: int,
) -> Dict[str, Any]:
    modules = [str(module).strip() for module in list(job.get("modules") or []) if str(module).strip()]
    source_id = str(job.get("source_id") or "")
    for module_name in modules:
        adapter = _build_legal_dataset_parser_adapter(
            module_name,
            retrieval_query,
            job=job,
            source_id=source_id,
            top_k=top_k,
        )
        if adapter:
            return adapter
    return {
        "adapter_ready": False,
        "module_name": modules[0] if modules else "",
        "requested_modules": modules,
        "reason": "No supported legal dataset parser adapter could be derived from this follow-up job.",
    }


def _build_legal_dataset_parser_adapter(
    module_name: str,
    retrieval_query: str,
    *,
    job: Mapping[str, Any],
    source_id: str,
    top_k: int,
) -> Dict[str, Any]:
    selected = _select_legal_dataset_parser_callable(
        module_name,
        retrieval_query,
        job=job,
        source_id=source_id,
        top_k=top_k,
    )
    if not selected:
        return {}

    module_path = _module_name_to_path(selected["module_name"])
    spec_available = False
    if module_path is None:
        try:
            spec_available = importlib.util.find_spec(selected["module_name"]) is not None
        except (ImportError, AttributeError, ValueError):
            spec_available = False

    adapter = {
        "adapter_ready": bool(module_path or spec_available),
        "adapter_kind": "parameterized_async_callable",
        "requested_module": module_name,
        "module_name": selected["module_name"],
        "module_path": str(module_path) if module_path is not None else "",
        "callable_name": selected["callable_name"],
        "callable_path": f"{selected['module_name']}:{selected['callable_name']}",
        "capability": selected["capability"],
        "query": retrieval_query,
        "top_k": int(top_k),
        "parameters": selected["parameters"],
        "invocation_target": {
            "module": selected["module_name"],
            "callable": selected["callable_name"],
            "awaitable": True,
        },
        "module_exists": module_path is not None,
        "spec_available": spec_available,
        "reason": selected["reason"],
    }
    if not adapter["adapter_ready"]:
        adapter["reason"] = (
            f"{selected['reason']} Module '{selected['module_name']}' could not be resolved locally."
        )
    return adapter


def _select_legal_dataset_parser_callable(
    module_name: str,
    retrieval_query: str,
    *,
    job: Mapping[str, Any],
    source_id: str,
    top_k: int,
) -> Dict[str, Any]:
    lowered_query = str(retrieval_query or "").lower()
    preferred_corpus_priority = [str(item).strip() for item in list(job.get("preferred_corpus_priority") or []) if str(item).strip()]
    preferred_corpus_keys = preferred_corpus_priority or [str(item).strip() for item in list(job.get("preferred_corpus_keys") or []) if str(item).strip()]
    preferred_dataset_priority = [str(item).strip() for item in list(job.get("preferred_dataset_priority") or []) if str(item).strip()]
    preferred_dataset_ids = preferred_dataset_priority or [str(item).strip() for item in list(job.get("preferred_dataset_ids") or []) if str(item).strip()]
    preferred_state_codes = [str(item).strip().upper() for item in list(job.get("preferred_state_codes") or []) if str(item).strip()]
    routing_reason = str(job.get("routing_reason") or "").strip()
    state_code = preferred_state_codes[0] if preferred_state_codes else "OR"

    def _with_routing_reason(reason: str) -> str:
        if routing_reason:
            return f"{reason} {routing_reason}"
        return reason

    def _preferred_state_parameters(corpus_key: str) -> Dict[str, Any]:
        canonical = get_canonical_legal_corpus(corpus_key)
        dataset_ids = preferred_dataset_ids or [canonical.hf_dataset_id]
        return {
            "state": state_code,
            "hf_dataset_id": dataset_ids[0],
            "hf_dataset_ids": dataset_ids,
            "hf_parquet_file": canonical.state_parquet_filename(state_code),
            "enrich_with_cases": False,
        }

    if "us_code" in preferred_corpus_keys:
        return {
            "module_name": module_name,
            "callable_name": "search_us_code_corpus_from_parameters",
            "capability": "us_code_corpus_search",
            "parameters": {
                "query_text": retrieval_query,
                "top_k": int(top_k),
                "hf_dataset_id": preferred_dataset_ids[0] if preferred_dataset_ids else None,
            },
            "reason": _with_routing_reason("Linked authority citations identify the US Code corpus as the preferred parser target."),
        }
    if "federal_register" in preferred_corpus_keys:
        return {
            "module_name": module_name,
            "callable_name": "search_federal_register_corpus_from_parameters",
            "capability": "federal_register_corpus_search",
            "parameters": {
                "query_text": retrieval_query,
                "top_k": int(top_k),
                "hf_dataset_id": preferred_dataset_ids[0] if preferred_dataset_ids else None,
            },
            "reason": _with_routing_reason("Linked authority citations identify the Federal Register corpus as the preferred parser target."),
        }
    if "state_court_rules" in preferred_corpus_keys:
        params = _preferred_state_parameters("state_court_rules")
        return {
            "module_name": module_name,
            "callable_name": "search_court_rules_corpus_from_parameters",
            "capability": "court_rules_corpus_search",
            "parameters": {
                "query_text": retrieval_query,
                "top_k": int(top_k),
                "jurisdiction": "state",
                **params,
            },
            "reason": _with_routing_reason("Linked authority citations identify state court rules as the preferred parser target."),
        }
    if "state_admin_rules" in preferred_corpus_keys and "state_laws" not in preferred_corpus_keys:
        params = _preferred_state_parameters("state_admin_rules")
        return {
            "module_name": module_name,
            "callable_name": "search_state_law_corpus_from_parameters",
            "capability": "state_admin_rule_corpus_search",
            "parameters": {
                "query_text": retrieval_query,
                "top_k": int(top_k),
                **params,
            },
            "reason": _with_routing_reason("Linked authority citations identify state administrative rules as the preferred parser target."),
        }
    if "state_laws" in preferred_corpus_keys or "state_admin_rules" in preferred_corpus_keys:
        params = _preferred_state_parameters("state_laws")
        if "state_admin_rules" in preferred_corpus_keys:
            admin_corpus = get_canonical_legal_corpus("state_admin_rules")
            params["hf_dataset_ids"] = list(dict.fromkeys([*params["hf_dataset_ids"], admin_corpus.hf_dataset_id]))
        return {
            "module_name": module_name,
            "callable_name": "search_state_law_corpus_from_parameters",
            "capability": "state_law_corpus_search",
            "parameters": {
                "query_text": retrieval_query,
                "top_k": int(top_k),
                **params,
            },
            "reason": _with_routing_reason("Linked authority citations identify state-law corpora as the preferred parser target."),
        }
    if module_name.endswith("legal_dataset_api"):
        if any(token in lowered_query for token in ("rule", "rules", "frcp", "civil procedure", "local rule", "court rule")):
            return {
                "module_name": module_name,
                "callable_name": "search_court_rules_corpus_from_parameters",
                "capability": "court_rules_corpus_search",
                "parameters": {
                    "query_text": retrieval_query,
                    "top_k": int(top_k),
                    "jurisdiction": "both",
                    "enrich_with_cases": True,
                },
                "reason": "Court-rule language in the proof gap maps to the court-rules corpus adapter.",
            }
        if any(token in lowered_query for token in ("register", "regulation", "regulations", "administrative", "agency", "cfr")):
            return {
                "module_name": module_name,
                "callable_name": "search_federal_register_corpus_from_parameters",
                "capability": "federal_register_corpus_search",
                "parameters": {
                    "query_text": retrieval_query,
                    "top_k": int(top_k),
                },
                "reason": "Regulatory language in the proof gap maps to the Federal Register corpus adapter.",
            }
        if any(token in lowered_query for token in ("u.s.c", "usc", "statute", "statutory", "code section", "section ")) or "§" in lowered_query:
            return {
                "module_name": module_name,
                "callable_name": "search_us_code_corpus_from_parameters",
                "capability": "us_code_corpus_search",
                "parameters": {
                    "query_text": retrieval_query,
                    "top_k": int(top_k),
                },
                "reason": "Statutory language in the proof gap maps to the US Code corpus adapter.",
            }
        return {
            "module_name": module_name,
            "callable_name": "search_state_law_corpus_from_parameters",
            "capability": "state_law_corpus_search",
            "parameters": {
                "query_text": retrieval_query,
                "top_k": int(top_k),
                "enrich_with_cases": False,
            },
            "reason": "General proof-gap language maps to the state-law corpus adapter as the default legal parser path.",
        }
    if module_name.endswith("recap_archive_scraper") or module_name.endswith("legal_web_archive_search"):
        return {
            "module_name": "ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api",
            "callable_name": "search_recap_documents_from_parameters",
            "capability": "recap_document_search",
            "parameters": {
                "query": retrieval_query,
                "limit": int(top_k),
                "case_name": source_id.split(":")[-1] if source_id else None,
            },
            "reason": "Docket-adjacent parser modules map to the RECAP document search adapter.",
        }
    if (
        module_name.endswith("multi_engine_legal_search")
        or module_name.endswith("brave_legal_search")
        or module_name.endswith("query_processor")
    ):
        return {
            "module_name": "ipfs_datasets_py.processors.legal_scrapers.multi_engine_legal_search",
            "callable_name": "multi_engine_legal_search",
            "capability": "multi_engine_legal_search",
            "parameters": {
                "query": retrieval_query,
                "max_results": int(top_k),
                "engines": ["duckduckgo", "brave"],
                "parallel_enabled": True,
                "fallback_enabled": True,
                "result_aggregation": "merge",
                "country": "US",
                "lang": "en",
            },
            "reason": "Search-orchestration modules map to the multi-engine legal search adapter.",
        }
    return {}


def _module_name_to_path(module_name: str) -> Optional[Path]:
    parts = [part for part in str(module_name or "").split(".") if part]
    if not parts or parts[0] != "ipfs_datasets_py":
        return None
    package_root = Path(__file__).resolve().parents[2]
    module_path = package_root.joinpath(*parts[1:]).with_suffix(".py")
    if module_path.exists():
        return module_path
    package_init = package_root.joinpath(*parts[1:], "__init__.py")
    if package_init.exists():
        return package_init
    return None


def _execute_legal_dataset_parser_adapter(adapter: Mapping[str, Any]) -> Dict[str, Any]:
    module_name = str(adapter.get("module_name") or "")
    callable_name = str(adapter.get("callable_name") or "")
    parameters = dict(adapter.get("parameters") or {})
    if not module_name or not callable_name:
        return {
            "executed": False,
            "reason": "Parser adapter is missing a module or callable name.",
            "results": [],
            "result_count": 0,
        }
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, callable_name)
    except Exception as exc:
        return {
            "executed": False,
            "reason": f"Could not load parser adapter target '{module_name}:{callable_name}': {exc}",
            "results": [],
            "result_count": 0,
        }

    try:
        if asyncio.iscoroutinefunction(target):
            parser_result = asyncio.run(target(parameters))
        else:
            parser_result = target(parameters)
    except Exception as exc:
        return {
            "executed": False,
            "reason": f"Parser adapter execution failed for '{module_name}:{callable_name}': {exc}",
            "results": [],
            "result_count": 0,
        }

    normalized = _normalize_legal_dataset_parser_result(parser_result)
    return {
        "executed": True,
        "reason": f"Executed parser adapter '{module_name}:{callable_name}'.",
        "results": normalized["results"],
        "result_count": normalized["result_count"],
        "parser_result": normalized["parser_result"],
    }


def _normalize_legal_dataset_parser_result(parser_result: Any) -> Dict[str, Any]:
    payload = parser_result if isinstance(parser_result, Mapping) else {"value": parser_result}
    results: List[Dict[str, Any]] = []
    if isinstance(payload.get("results"), list):
        for item in payload.get("results") or []:
            if isinstance(item, Mapping):
                results.append(dict(item))
            else:
                results.append({"value": item})
    elif isinstance(payload.get("documents"), list):
        for item in payload.get("documents") or []:
            if isinstance(item, Mapping):
                results.append(dict(item))
            else:
                results.append({"value": item})
    elif isinstance(payload.get("hits"), list):
        for item in payload.get("hits") or []:
            if isinstance(item, Mapping):
                results.append(dict(item))
            else:
                results.append({"value": item})

    if not results and isinstance(payload, Mapping):
        content_keys = {"status", "error", "message", "metadata", "query", "operation", "tool_version"}
        residual = {str(key): value for key, value in payload.items() if key not in content_keys}
        if residual:
            results = [residual]

    count = payload.get("count")
    if count is None:
        count = payload.get("total_results")
    if count is None:
        count = len(results)
    return {
        "results": results,
        "result_count": int(count or 0),
        "parser_result": dict(payload) if isinstance(payload, Mapping) else {"value": payload},
    }


__all__ = [
    "DocketDatasetPackager",
    "PackagedQueryExecutionPlan",
    "PackagedDocketQueryAdapter",
    "execute_packaged_docket_query",
    "execute_packaged_docket_follow_up_job",
    "execute_packaged_docket_follow_up_plan",
    "iter_packaged_docket_chain",
    "inspect_packaged_docket_bundle",
    "load_packaged_docket_dataset",
    "load_packaged_docket_dataset_components",
    "load_packaged_docket_summary_view",
    "load_packaged_docket_inspection_report",
    "plan_packaged_docket_query",
    "prepare_packaged_docket_follow_up_job",
    "package_docket_dataset",
    "render_packaged_docket_inspection_report",
    "search_packaged_docket_dataset_bm25",
    "search_packaged_docket_dataset_vector",
    "get_packaged_docket_proof_revalidation_queue",
    "search_packaged_docket_proof_tasks",
    "search_packaged_docket_logic_artifacts",
]
