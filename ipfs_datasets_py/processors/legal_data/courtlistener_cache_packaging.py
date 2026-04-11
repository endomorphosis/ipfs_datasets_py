"""Packaging helpers for CourtListener shared fetch cache artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Sequence
import zipfile

import pyarrow.parquet as pq
from .docket_packaging import _digest_file, _safe_identifier, _write_rows_to_parquet
from ..serialization.car_conversion import DataInterchangeUtils
from ..storage.ipld.storage import IPLDStorage


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_cache_rows(cache_dir: Path) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    index_rows: List[Dict[str, Any]] = []
    payload_rows: List[Dict[str, Any]] = []
    for namespace_dir in sorted(path for path in cache_dir.iterdir() if path.is_dir()):
        namespace = namespace_dir.name
        index_dir = namespace_dir / "index"
        payload_dir = namespace_dir / "payload"
        for index_path in sorted(index_dir.glob("*.json")) if index_dir.exists() else []:
            index_payload = _load_json(index_path)
            cache_key = str(index_payload.get("cache_key") or index_path.stem)
            index_rows.append(
                {
                    "namespace": namespace,
                    "cache_key": cache_key,
                    "url": str(index_payload.get("url") or ""),
                    "normalized_url": str(index_payload.get("normalized_url") or ""),
                    "cached_at": str(index_payload.get("cached_at") or ""),
                    "payload_path": str(index_payload.get("payload_path") or ""),
                    "ipfs_cid": str(index_payload.get("ipfs_cid") or ""),
                    "index_json": json.dumps(index_payload, sort_keys=True),
                }
            )
        for payload_path in sorted(payload_dir.glob("*.json")) if payload_dir.exists() else []:
            payload = _load_json(payload_path)
            payload_rows.append(
                {
                    "namespace": namespace,
                    "cache_key": payload_path.stem,
                    "payload_json": json.dumps(payload, sort_keys=True),
                    "has_content_base64": bool(payload.get("content_base64")),
                    "sha256": str(payload.get("sha256") or ""),
                    "size": int(payload.get("size") or 0),
                    "url": str(payload.get("url") or ""),
                }
            )
    return index_rows, payload_rows


def package_courtlistener_fetch_cache(
    cache_dir: str | Path,
    output_dir: str | Path,
    *,
    package_name: str | None = None,
    include_car: bool = True,
) -> Dict[str, Any]:
    """Package CourtListener shared fetch cache entries into Parquet/CAR artifacts."""

    cache_root = Path(cache_dir)
    if not cache_root.exists():
        raise FileNotFoundError(f"CourtListener cache directory does not exist: {cache_root}")

    index_rows, payload_rows = _build_cache_rows(cache_root)
    output_root = Path(output_dir)
    bundle_name = package_name or "courtlistener_cache_bundle"
    bundle_dir = output_root / _safe_identifier(bundle_name)
    parquet_dir = bundle_dir / "parquet"
    car_dir = bundle_dir / "car"
    parquet_dir.mkdir(parents=True, exist_ok=True)
    if include_car:
        car_dir.mkdir(parents=True, exist_ok=True)

    car_utils = DataInterchangeUtils(storage=IPLDStorage())
    pieces: List[Dict[str, Any]] = []
    rows_by_piece = {
        "cache_index": index_rows,
        "cache_payloads": payload_rows,
    }
    for piece_id, rows in rows_by_piece.items():
        parquet_path = parquet_dir / f"{piece_id}.parquet"
        write_meta = _write_rows_to_parquet(rows, parquet_path)
        piece = {
            "piece_id": piece_id,
            "group": "courtlistener_cache",
            "row_count": int(write_meta["row_count"]),
            "schema": list(write_meta["schema"]),
            "parquet_path": str(parquet_path.relative_to(bundle_dir)),
            "car_path": "",
            "root_cid": "",
            "sha256": _digest_file(parquet_path),
            "depends_on": [] if piece_id == "cache_index" else ["cache_index"],
        }
        if include_car:
            car_path = car_dir / f"{piece_id}.car"
            try:
                piece["root_cid"] = str(car_utils.parquet_to_car(str(parquet_path), str(car_path)))
                piece["car_path"] = str(car_path.relative_to(bundle_dir))
            except Exception:
                piece["root_cid"] = ""
                piece["car_path"] = ""
        pieces.append(piece)

    manifest = {
        "bundle_name": bundle_name,
        "bundle_type": "courtlistener_fetch_cache",
        "piece_count": len(pieces),
        "chain_load_order": [piece["piece_id"] for piece in pieces],
        "pieces": pieces,
        "summary": {
            "cache_index_count": len(index_rows),
            "cache_payload_count": len(payload_rows),
            "binary_payload_count": sum(1 for row in payload_rows if bool(row.get("has_content_base64"))),
            "mirrored_ipfs_entry_count": sum(1 for row in index_rows if str(row.get("ipfs_cid") or "").strip()),
        },
    }

    manifest_json_path = bundle_dir / "bundle_manifest.json"
    manifest_json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest_parquet_path = parquet_dir / "bundle_manifest.parquet"
    _write_rows_to_parquet(
        [
            {
                "bundle_name": bundle_name,
                "bundle_type": manifest["bundle_type"],
                "manifest_json": json.dumps(manifest, sort_keys=True),
            }
        ],
        manifest_parquet_path,
    )

    manifest_car_path = ""
    manifest_root_cid = ""
    if include_car:
        manifest_car = car_dir / "bundle_manifest.car"
        try:
            manifest_root_cid = str(car_utils.parquet_to_car(str(manifest_parquet_path), str(manifest_car)))
            manifest_car_path = str(manifest_car.relative_to(bundle_dir))
            manifest["manifest_root_cid"] = manifest_root_cid
            manifest["manifest_car_path"] = manifest_car_path
            manifest_json_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            manifest_root_cid = ""
            manifest_car_path = ""

    return {
        "bundle_dir": str(bundle_dir),
        "manifest_json_path": str(manifest_json_path),
        "manifest_parquet_path": str(manifest_parquet_path),
        "manifest_car_path": str(bundle_dir / manifest_car_path) if manifest_car_path else "",
        "manifest_root_cid": manifest_root_cid,
        "piece_count": len(pieces),
        "pieces": pieces,
        "summary": dict(manifest["summary"]),
    }


class CourtListenerCachePackager:
    """Load packaged CourtListener fetch cache bundles from json/parquet/car/zip manifests."""

    def __init__(self) -> None:
        self._car_utils = DataInterchangeUtils(storage=IPLDStorage())
        self._temp_bundle_dirs: Dict[str, tempfile.TemporaryDirectory[str]] = {}
        self._temp_piece_dirs: Dict[str, tempfile.TemporaryDirectory[str]] = {}

    def load_package(self, manifest_path: str | Path) -> Dict[str, Any]:
        bundle_dir, manifest = self._resolve_manifest(manifest_path)
        rows_by_piece = self.load_package_components(bundle_dir, manifest=manifest)
        return {
            "bundle_manifest": dict(manifest),
            "cache_index": list(rows_by_piece.get("cache_index") or []),
            "cache_payloads": list(rows_by_piece.get("cache_payloads") or []),
            "summary": dict(manifest.get("summary") or {}),
        }

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
            resolved_manifest = dict(manifest) if manifest is not None else json.loads(manifest_file.read_text(encoding="utf-8"))
            return bundle_dir, resolved_manifest
        suffix = path.suffix.lower()
        if suffix == ".zip":
            return self._resolve_zipped_manifest(path, manifest=manifest)
        if suffix == ".parquet":
            bundle_dir = self._bundle_dir_from_manifest_sidecar(path)
            resolved_manifest = dict(manifest) if manifest is not None else self._load_manifest_from_parquet(path)
            return bundle_dir, resolved_manifest
        if suffix == ".car":
            bundle_dir = self._bundle_dir_from_manifest_sidecar(path)
            manifest_parquet = self._materialize_manifest_parquet_from_car(path)
            resolved_manifest = dict(manifest) if manifest is not None else self._load_manifest_from_parquet(manifest_parquet)
            return bundle_dir, resolved_manifest
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
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="courtlistener_cache_zip_", dir=safe_temp_root)
            with zipfile.ZipFile(archive_path, "r") as archive:
                archive.extractall(temp_dir_obj.name)
            self._temp_bundle_dirs[cache_key] = temp_dir_obj
        extracted_root = Path(temp_dir_obj.name)
        manifest_candidates = sorted(extracted_root.rglob("bundle_manifest.json"))
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
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="courtlistener_cache_manifest_car_", dir=safe_temp_root)
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
            temp_dir_obj = tempfile.TemporaryDirectory(prefix="courtlistener_cache_piece_car_", dir=safe_temp_root)
            self._temp_piece_dirs[cache_key] = temp_dir_obj
        temp_dir = Path(temp_dir_obj.name)
        piece_parquet_path = temp_dir / f"{str(piece.get('piece_id') or 'piece')}.parquet"
        if not piece_parquet_path.exists():
            self._car_utils.car_to_parquet(str(car_path), str(piece_parquet_path))
        return piece_parquet_path


def load_packaged_courtlistener_fetch_cache(manifest_path: str | Path) -> Dict[str, Any]:
    return CourtListenerCachePackager().load_package(manifest_path)


def load_packaged_courtlistener_fetch_cache_components(
    manifest_path: str | Path,
    *,
    piece_ids: Optional[Sequence[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    return CourtListenerCachePackager().load_package_components(manifest_path, piece_ids=piece_ids)
