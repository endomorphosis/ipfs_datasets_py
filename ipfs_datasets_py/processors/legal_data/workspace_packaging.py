"""Parquet and CAR packaging helpers for workspace datasets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..serialization.car_conversion import DataInterchangeUtils
from ..storage.ipld.storage import IPLDStorage


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


def _is_zkp_certificate(certificate: Mapping[str, Any]) -> bool:
    backend = str(certificate.get("backend") or "").lower()
    fmt = str(certificate.get("format") or "").lower()
    payload = certificate.get("payload") if isinstance(certificate.get("payload"), Mapping) else {}
    proof_system = str((payload or {}).get("proof_system") or "").lower()
    return (
        "zkp" in backend
        or "zkp" in fmt
        or "groth16" in backend
        or "groth16" in fmt
        or "groth16" in proof_system
        or "zksnark" in fmt
    )


def _extract_zkp_proof_certificates(metadata: Mapping[str, Any]) -> List[Dict[str, Any]]:
    formal_logic = dict(metadata.get("formal_logic") or {})
    proof_store = dict(formal_logic.get("proof_store") or {})
    certificates = [dict(item) for item in list(proof_store.get("certificates") or []) if isinstance(item, Mapping)]
    explicit = [dict(item) for item in list(formal_logic.get("zkp_proof_certificates") or []) if isinstance(item, Mapping)]
    by_id: Dict[str, Dict[str, Any]] = {}
    for certificate in explicit + certificates:
        if not _is_zkp_certificate(certificate):
            continue
        certificate_id = str(certificate.get("certificate_id") or "")
        by_id[certificate_id or f"zkp_certificate_{len(by_id) + 1}"] = certificate
    return list(by_id.values())


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _write_rows_to_parquet(rows: Sequence[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        field_names: List[str] = []
        seen = set()
        for row in rows:
            for key in row.keys():
                name = str(key)
                if name not in seen:
                    seen.add(name)
                    field_names.append(name)
        normalized_rows = [
            _normalize_parquet_row({name: row.get(name) for name in field_names})
            for row in rows
        ]
    else:
        normalized_rows = [{"_empty": True}]
    table = pa.Table.from_pylist(normalized_rows)
    pq.write_table(table, output_path)
    return {
        "row_count": 0 if rows == [] else len(rows),
        "schema": [{"name": field.name, "type": str(field.type)} for field in table.schema],
    }


def _parse_possible_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or (not text.startswith("{") and not text.startswith("[")):
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _restore_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    decoded: List[Dict[str, Any]] = []
    json_fields = {"metadata", "properties", "attributes", "vector", "raw"}
    for row in rows:
        payload: Dict[str, Any] = {}
        for key, value in dict(row).items():
            if key.endswith("_json"):
                payload[key] = _parse_possible_json(value)
                continue
            if key in json_fields:
                payload[key] = _parse_possible_json(value)
                continue
            payload[key] = value
        decoded.append(payload)
    return decoded


@dataclass
class WorkspacePackagePiece:
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


class WorkspaceDatasetPackager:
    """Package workspace datasets into chain-loadable Parquet and CAR artifacts."""

    def __init__(self) -> None:
        self._car_utils = DataInterchangeUtils(storage=IPLDStorage())

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
        bundle_name = package_name or str(dataset_payload.get("dataset_id") or "workspace_dataset_bundle")
        legacy_layout = package_name is None
        bundle_dir = output_root if legacy_layout else output_root / _safe_identifier(bundle_name)
        parquet_dir = bundle_dir if legacy_layout else bundle_dir / "parquet"
        car_dir = bundle_dir if legacy_layout else bundle_dir / "car"
        parquet_dir.mkdir(parents=True, exist_ok=True)
        if include_car:
            car_dir.mkdir(parents=True, exist_ok=True)

        documents = [dict(item) for item in list(dataset_payload.get("documents") or []) if isinstance(item, dict)]
        collections = [dict(item) for item in list(dataset_payload.get("collections") or []) if isinstance(item, dict)]
        knowledge_graph = dict(dataset_payload.get("knowledge_graph") or {})
        bm25_documents = [dict(item) for item in list((dataset_payload.get("bm25_index") or {}).get("documents") or []) if isinstance(item, dict)]
        vector_items = [dict(item) for item in list((dataset_payload.get("vector_index") or {}).get("items") or []) if isinstance(item, dict)]
        metadata = dict(dataset_payload.get("metadata") or {})
        formal_summary = dict(metadata.get("formal_logic_summary") or (metadata.get("formal_logic") or {}).get("summary") or {})
        zkp_proof_certificates = _extract_zkp_proof_certificates(metadata)
        zkp_proof_certificate_ids = [
            str(item.get("certificate_id") or "")
            for item in zkp_proof_certificates
            if str(item.get("certificate_id") or "")
        ]
        artifact_provenance = dict(metadata.get("artifact_provenance") or {})
        workspace_input_provenance = dict(artifact_provenance.get("workspace_input") or {})
        input_type = str(workspace_input_provenance.get("input_type") or "")
        input_type_resolution = str(workspace_input_provenance.get("input_type_resolution") or "")

        section_rows: List[tuple[str, str, List[Dict[str, Any]], List[str]]] = [
            (
                "dataset_core",
                "dataset",
                [
                    {
                        "dataset_id": str(dataset_payload.get("dataset_id") or ""),
                        "workspace_id": str(dataset_payload.get("workspace_id") or ""),
                        "workspace_name": str(dataset_payload.get("workspace_name") or ""),
                        "source_type": str(dataset_payload.get("source_type") or "workspace"),
                        "metadata_json": json.dumps(_jsonable(metadata), sort_keys=True),
                    }
                ],
                [],
            ),
            ("collections", "collections", collections, ["dataset_core"]),
            ("documents", "documents", documents, ["dataset_core"]),
            (
                "knowledge_graph_entities",
                "knowledge_graph",
                [dict(item) for item in list(knowledge_graph.get("entities") or []) if isinstance(item, dict)],
                ["dataset_core"],
            ),
            (
                "knowledge_graph_relationships",
                "knowledge_graph",
                [dict(item) for item in list(knowledge_graph.get("relationships") or []) if isinstance(item, dict)],
                ["knowledge_graph_entities"],
            ),
            ("bm25_documents", "bm25_index", bm25_documents, ["documents"]),
            ("vector_items", "vector_index", vector_items, ["documents"]),
            ("zkp_proof_certificates", "formal_logic", zkp_proof_certificates, ["dataset_core"]),
        ]

        pieces: List[WorkspacePackagePiece] = []
        for piece_id, group, rows, depends_on in section_rows:
            parquet_path = parquet_dir / f"{piece_id}.parquet"
            parquet_meta = _write_rows_to_parquet(rows, parquet_path)
            piece = WorkspacePackagePiece(
                piece_id=piece_id,
                parquet_path=str(parquet_path.relative_to(bundle_dir)),
                row_count=int(parquet_meta.get("row_count") or 0),
                group=group,
                schema=list(parquet_meta.get("schema") or []),
                depends_on=list(depends_on),
                sha256=_digest_file(parquet_path),
            )
            if include_car:
                car_path = car_dir / f"{piece_id}.car"
                piece.root_cid = str(self._car_utils.parquet_to_car(str(parquet_path), str(car_path)))
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
            "workspace_id": str(dataset_payload.get("workspace_id") or ""),
            "workspace_name": str(dataset_payload.get("workspace_name") or ""),
            "source_type": str(dataset_payload.get("source_type") or "workspace"),
            "input_type": input_type,
            "input_type_resolution": input_type_resolution,
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
                "collection_count": len(collections),
                "knowledge_graph_entity_count": len(list(knowledge_graph.get("entities") or [])),
                "knowledge_graph_relationship_count": len(list(knowledge_graph.get("relationships") or [])),
                "bm25_document_count": len(bm25_documents),
                "vector_document_count": len(vector_items),
                "formal_logic_processed_document_count": int(formal_summary.get("processed_document_count") or 0),
                "deontic_statement_count": int(formal_summary.get("deontic_statement_count") or 0),
                "temporal_formula_count": int(formal_summary.get("temporal_formula_count") or 0),
                "first_order_formula_count": int(formal_summary.get("first_order_formula_count") or 0),
                "dcec_formula_count": int(formal_summary.get("dcec_formula_count") or 0),
                "frame_logic_count": int(formal_summary.get("frame_count") or 0),
                "proof_count": int(formal_summary.get("proof_count") or 0),
                "proof_certificate_count": int(formal_summary.get("proof_certificate_count") or 0),
                "zkp_certificate_count": int(formal_summary.get("zkp_certificate_count") or len(zkp_proof_certificates)),
                "zkp_proof_certificate_ids": list(formal_summary.get("zkp_proof_certificate_ids") or zkp_proof_certificate_ids),
                "zkp_backend": str(formal_summary.get("zkp_backend") or ""),
                "zkp_available": bool(formal_summary.get("zkp_available")),
                "logic_systems": _jsonable(dict(formal_summary.get("logic_systems") or {})),
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
                    "workspace_id": manifest["workspace_id"],
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
            "input_type": input_type,
            "input_type_resolution": input_type_resolution,
            "piece_count": len(pieces),
            "pieces": [piece.to_dict() for piece in pieces],
            "summary": dict(manifest["summary"]),
        }

    def _resolve_manifest(self, manifest_path: str | Path) -> tuple[Path, Dict[str, Any]]:
        path = Path(manifest_path)
        if path.is_dir():
            bundle_dir = path
            json_path = bundle_dir / "bundle_manifest.json"
            if not json_path.exists():
                json_path = bundle_dir / "manifest.json"
        else:
            json_path = path
            bundle_dir = path.parent
        manifest = json.loads(json_path.read_text(encoding="utf-8"))
        return bundle_dir, dict(manifest)

    def load_package_components(
        self,
        manifest_path: str | Path,
        *,
        piece_ids: Optional[Sequence[str]] = None,
        manifest: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        bundle_dir, manifest_payload = self._resolve_manifest(manifest_path) if manifest is None else (Path(manifest_path), manifest)
        piece_map = {
            str(piece.get("piece_id") or ""): dict(piece)
            for piece in list(manifest_payload.get("pieces") or [])
            if str(piece.get("piece_id") or "")
        }
        targets = list(piece_ids) if piece_ids is not None else list(piece_map.keys())
        rows_by_piece: Dict[str, List[Dict[str, Any]]] = {}
        for piece_id in targets:
            piece = piece_map.get(str(piece_id) or "")
            if piece is None:
                continue
            parquet_path = bundle_dir / str(piece.get("parquet_path") or "")
            table = pq.read_table(parquet_path)
            rows_by_piece[str(piece_id)] = [dict(row) for row in table.to_pylist()]
        return rows_by_piece

    def load_package(self, manifest_path: str | Path) -> Dict[str, Any]:
        bundle_dir, manifest = self._resolve_manifest(manifest_path)
        rows_by_piece = self.load_package_components(bundle_dir, manifest=manifest)
        dataset_core = dict((rows_by_piece.get("dataset_core") or [{}])[0])
        metadata = _parse_possible_json(dataset_core.get("metadata_json")) or {}
        return {
            "dataset_id": str(dataset_core.get("dataset_id") or manifest.get("dataset_id") or ""),
            "workspace_id": str(dataset_core.get("workspace_id") or manifest.get("workspace_id") or ""),
            "workspace_name": str(dataset_core.get("workspace_name") or manifest.get("workspace_name") or ""),
            "source_type": str(dataset_core.get("source_type") or manifest.get("source_type") or "workspace"),
            "input_type": str(manifest.get("input_type") or ""),
            "input_type_resolution": str(manifest.get("input_type_resolution") or ""),
            "documents": _restore_rows(rows_by_piece.get("documents") or []),
            "collections": _restore_rows(rows_by_piece.get("collections") or []),
            "zkp_proof_certificates": _restore_rows(rows_by_piece.get("zkp_proof_certificates") or []),
            "knowledge_graph": {
                "entities": _restore_rows(rows_by_piece.get("knowledge_graph_entities") or []),
                "relationships": _restore_rows(rows_by_piece.get("knowledge_graph_relationships") or []),
            },
            "bm25_index": {
                "backend": "local_bm25",
                "documents": _restore_rows(rows_by_piece.get("bm25_documents") or []),
            },
            "vector_index": {
                "backend": "local_hashed_term_projection",
                "items": _restore_rows(rows_by_piece.get("vector_items") or []),
            },
            "metadata": dict(metadata),
            "bundle": {
                "manifest_path": str(bundle_dir),
                "piece_count": len(list(manifest.get("pieces") or [])),
            },
        }

    def _load_collection_overview(self, bundle_dir: Path, manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
        rows = self.load_package_components(bundle_dir, piece_ids=["collections"], manifest=dict(manifest)).get("collections") or []
        collections = _restore_rows(rows)
        overview: List[Dict[str, Any]] = []
        for collection in collections:
            document_ids = _parse_possible_json(collection.get("document_ids")) or []
            if not isinstance(document_ids, list):
                document_ids = []
            overview.append(
                {
                    "id": str(collection.get("id") or ""),
                    "title": str(collection.get("title") or ""),
                    "source_type": str(collection.get("source_type") or ""),
                    "parent_document_id": str(collection.get("parent_document_id") or ""),
                    "document_count": len(document_ids),
                }
            )
        return overview

    def load_summary_view(self, manifest_path: str | Path) -> Dict[str, Any]:
        bundle_dir, manifest = self._resolve_manifest(manifest_path)
        summary = dict(manifest.get("summary") or {})
        return {
            "dataset_id": str(manifest.get("dataset_id") or ""),
            "workspace_id": str(manifest.get("workspace_id") or ""),
            "workspace_name": str(manifest.get("workspace_name") or ""),
            "source_type": str(manifest.get("source_type") or "workspace"),
            "input_type": str(manifest.get("input_type") or ""),
            "input_type_resolution": str(manifest.get("input_type_resolution") or ""),
            "document_count": int(summary.get("document_count") or 0),
            "collection_count": int(summary.get("collection_count") or 0),
            "knowledge_graph_entity_count": int(summary.get("knowledge_graph_entity_count") or 0),
            "knowledge_graph_relationship_count": int(summary.get("knowledge_graph_relationship_count") or 0),
            "bm25_document_count": int(summary.get("bm25_document_count") or 0),
            "vector_document_count": int(summary.get("vector_document_count") or 0),
            "formal_logic_processed_document_count": int(summary.get("formal_logic_processed_document_count") or 0),
            "deontic_statement_count": int(summary.get("deontic_statement_count") or 0),
            "temporal_formula_count": int(summary.get("temporal_formula_count") or 0),
            "first_order_formula_count": int(summary.get("first_order_formula_count") or 0),
            "dcec_formula_count": int(summary.get("dcec_formula_count") or 0),
            "frame_logic_count": int(summary.get("frame_logic_count") or 0),
            "proof_count": int(summary.get("proof_count") or 0),
            "proof_certificate_count": int(summary.get("proof_certificate_count") or 0),
            "zkp_certificate_count": int(summary.get("zkp_certificate_count") or 0),
            "zkp_proof_certificate_ids": [
                str(item)
                for item in list(summary.get("zkp_proof_certificate_ids") or [])
                if str(item or "")
            ],
            "zkp_backend": str(summary.get("zkp_backend") or ""),
            "zkp_available": bool(summary.get("zkp_available")),
            "logic_systems": dict(summary.get("logic_systems") or {}),
            "collection_overview": self._load_collection_overview(bundle_dir, manifest),
            "package_manifest": dict(manifest),
        }

    def inspect_packaged_bundle(self, manifest_path: str | Path) -> Dict[str, Any]:
        summary = self.load_summary_view(manifest_path)
        manifest = dict(summary.get("package_manifest") or {})
        return {
            "dataset_id": summary.get("dataset_id"),
            "workspace_id": summary.get("workspace_id"),
            "workspace_name": summary.get("workspace_name"),
            "source_type": summary.get("source_type"),
            "input_type": summary.get("input_type"),
            "input_type_resolution": summary.get("input_type_resolution"),
            "document_count": summary.get("document_count"),
            "collection_count": summary.get("collection_count"),
            "collection_overview": list(summary.get("collection_overview") or []),
            "knowledge_graph_entity_count": summary.get("knowledge_graph_entity_count"),
            "knowledge_graph_relationship_count": summary.get("knowledge_graph_relationship_count"),
            "bm25_document_count": summary.get("bm25_document_count"),
            "vector_document_count": summary.get("vector_document_count"),
            "formal_logic_processed_document_count": summary.get("formal_logic_processed_document_count"),
            "deontic_statement_count": summary.get("deontic_statement_count"),
            "temporal_formula_count": summary.get("temporal_formula_count"),
            "first_order_formula_count": summary.get("first_order_formula_count"),
            "dcec_formula_count": summary.get("dcec_formula_count"),
            "frame_logic_count": summary.get("frame_logic_count"),
            "proof_count": summary.get("proof_count"),
            "proof_certificate_count": summary.get("proof_certificate_count"),
            "zkp_certificate_count": summary.get("zkp_certificate_count"),
            "zkp_proof_certificate_ids": list(summary.get("zkp_proof_certificate_ids") or []),
            "zkp_backend": summary.get("zkp_backend"),
            "zkp_available": summary.get("zkp_available"),
            "logic_systems": dict(summary.get("logic_systems") or {}),
            "piece_count": int(manifest.get("piece_count") or 0),
            "source": "packaged_workspace_dataset_inspection",
        }


def load_packaged_workspace_dataset(manifest_path: str | Path) -> Dict[str, Any]:
    return WorkspaceDatasetPackager().load_package(manifest_path)


def load_packaged_workspace_dataset_components(
    manifest_path: str | Path,
    *,
    piece_ids: Optional[Sequence[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    return WorkspaceDatasetPackager().load_package_components(manifest_path, piece_ids=piece_ids)


def load_packaged_workspace_summary_view(manifest_path: str | Path) -> Dict[str, Any]:
    return WorkspaceDatasetPackager().load_summary_view(manifest_path)


def inspect_packaged_workspace_bundle(manifest_path: str | Path) -> Dict[str, Any]:
    return WorkspaceDatasetPackager().inspect_packaged_bundle(manifest_path)


def iter_packaged_workspace_chain(manifest_path: str | Path) -> List[Dict[str, Any]]:
    _, manifest = WorkspaceDatasetPackager()._resolve_manifest(manifest_path)
    piece_map = {
        str(piece.get("piece_id") or ""): dict(piece)
        for piece in list(manifest.get("pieces") or [])
        if str(piece.get("piece_id") or "")
    }
    ordered: List[Dict[str, Any]] = []
    for piece_id in list(manifest.get("chain_load_order") or []):
        piece = piece_map.get(str(piece_id) or "")
        if piece is not None:
            ordered.append(piece)
    if ordered:
        return ordered
    return [dict(piece) for piece in list(manifest.get("pieces") or [])]


def render_packaged_workspace_report(
    manifest_path: str | Path | Dict[str, Any],
    *,
    report_format: str = "markdown",
) -> str:
    inspection = (
        dict(manifest_path)
        if isinstance(manifest_path, dict)
        else inspect_packaged_workspace_bundle(manifest_path)
    )
    normalized_format = str(report_format or "markdown").strip().lower()
    if normalized_format == "json":
        return json.dumps(inspection, indent=2, ensure_ascii=False) + "\n"

    lines = [
        "Packaged Workspace Dataset Report",
        f"Workspace ID: {str(inspection.get('workspace_id') or '')}",
        f"Workspace Name: {str(inspection.get('workspace_name') or '')}",
        f"Source Type: {str(inspection.get('source_type') or '')}",
        f"Input Type: {str(inspection.get('input_type') or '')}",
        f"Input Type Resolution: {str(inspection.get('input_type_resolution') or '')}",
        f"Document Count: {int(inspection.get('document_count') or 0)}",
        f"Collection Count: {int(inspection.get('collection_count') or 0)}",
        f"Knowledge Graph Entities: {int(inspection.get('knowledge_graph_entity_count') or 0)}",
        f"Knowledge Graph Relationships: {int(inspection.get('knowledge_graph_relationship_count') or 0)}",
        f"BM25 Documents: {int(inspection.get('bm25_document_count') or 0)}",
        f"Vector Documents: {int(inspection.get('vector_document_count') or 0)}",
        f"Piece Count: {int(inspection.get('piece_count') or 0)}",
    ]
    collection_overview = [dict(item) for item in list(inspection.get("collection_overview") or []) if isinstance(item, Mapping)]
    if collection_overview:
        lines.append("Collection Overview:")
        for item in collection_overview:
            lines.append(
                "  - "
                f"{str(item.get('id') or '')}"
                f" [{str(item.get('source_type') or '')}]"
                f" ({int(item.get('document_count') or 0)} docs)"
            )
    if normalized_format == "text":
        return "\n".join(lines) + "\n"
    if normalized_format == "markdown":
        markdown_lines = [
            "# Packaged Workspace Dataset Report",
            "",
            *[f"- {line}" for line in lines[1:]],
        ]
        return "\n".join(markdown_lines) + "\n"
    raise ValueError(f"Unsupported packaged workspace report format: {report_format}")


def package_workspace_dataset(
    dataset: Any,
    output_dir: str | Path,
    *,
    package_name: str | None = None,
    include_car: bool = True,
) -> Dict[str, Any]:
    return WorkspaceDatasetPackager().package(
        dataset,
        output_dir,
        package_name=package_name,
        include_car=include_car,
    )


def export_packaged_workspace_hf_records_parquet(
    manifest_path: str | Path,
    output_path: str | Path,
) -> Dict[str, Any]:
    """Export a packaged workspace bundle as one flat, portable record table.

    Workspace packages are internally relational: documents, collections,
    graph rows, search rows, vectors, and ZKP certificates each have distinct
    schemas. This exporter preserves every packaged component as section-tagged
    rows in a single Parquet file that can be queried lazily or shared as one
    Hugging Face-friendly dataset artifact.
    """

    packager = WorkspaceDatasetPackager()
    bundle_dir, manifest = packager._resolve_manifest(manifest_path)
    rows_by_piece = packager.load_package_components(bundle_dir, manifest=manifest)
    dataset_id = str(manifest.get("dataset_id") or "")
    workspace_id = str(manifest.get("workspace_id") or "")
    workspace_name = str(manifest.get("workspace_name") or "")
    source_type = str(manifest.get("source_type") or "workspace")

    def _pick_row_id(piece_id: str, payload: Mapping[str, Any], index: int) -> str:
        for key in (
            "document_id",
            "id",
            "entity_id",
            "relationship_id",
            "certificate_id",
        ):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return f"{piece_id}_{index}"

    def _pick_parent_id(payload: Mapping[str, Any]) -> str:
        for key in (
            "parent_document_id",
            "document_id",
            "source",
            "target",
            "source_id",
            "collection_id",
        ):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def _pick_title(payload: Mapping[str, Any]) -> str:
        for key in ("title", "label", "workspace_name", "theorem"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def _pick_text(payload: Mapping[str, Any]) -> str:
        for key in ("text", "content", "body", "description", "theorem"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    def _pick_source_url(payload: Mapping[str, Any]) -> str:
        for key in ("source_url", "path_or_url", "source_path", "source_ref"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    hf_rows: List[Dict[str, Any]] = []
    section_counts: Dict[str, int] = {}
    ordered_piece_ids = [
        str(piece.get("piece_id") or "")
        for piece in list(manifest.get("pieces") or [])
        if str(piece.get("piece_id") or "")
    ]
    for piece_id in ordered_piece_ids:
        rows = [dict(row) for row in list(rows_by_piece.get(piece_id) or []) if isinstance(row, Mapping)]
        section_counts[piece_id] = len(rows)
        for index, row in enumerate(rows, start=1):
            metadata = row.get("metadata")
            metadata_json = metadata if isinstance(metadata, str) else json.dumps(_jsonable(metadata or {}), sort_keys=True)
            hf_rows.append(
                {
                    "dataset_id": dataset_id,
                    "workspace_id": workspace_id,
                    "workspace_name": workspace_name,
                    "source_type": source_type,
                    "record_type": piece_id,
                    "section": piece_id,
                    "row_index": index,
                    "record_id": _pick_row_id(piece_id, row, index),
                    "row_id": _pick_row_id(piece_id, row, index),
                    "parent_id": _pick_parent_id(row),
                    "title": _pick_title(row),
                    "document_number": str(row.get("document_number") or ""),
                    "source_url": _pick_source_url(row),
                    "text": _pick_text(row),
                    "metadata_json": metadata_json,
                    "payload_json": json.dumps(_jsonable(row), sort_keys=True),
                }
            )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_meta = _write_rows_to_parquet(hf_rows, output_path)
    return {
        "parquet_path": str(output_path),
        "row_count": int(write_meta["row_count"]),
        "schema": list(write_meta["schema"]),
        "sha256": _digest_file(output_path),
        "section_counts": section_counts,
        "source_manifest_path": str(manifest_path),
        "source_bundle_dir": str(bundle_dir),
        "format": "workspace_hf_records_v1",
    }
