"""Promotion helpers for turning recovery manifests into structured canonical rows."""

from __future__ import annotations

import json
from pathlib import Path
import shlex
from typing import Any, Dict, List, Mapping, Optional

from .canonical_legal_corpora import get_canonical_legal_corpus


_MERGE_KEY_FIELDS = (
    "source_type",
    "corpus_key",
    "normalized_citation",
    "primary_candidate_url",
    "manifest_path",
)


def _normalize_rows_for_table(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return [{"_empty": True}]

    field_names: List[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                field_names.append(key)

    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalized_rows.append({key: row.get(key) for key in field_names})
    return normalized_rows


def _read_rows_from_parquet(parquet_path: Path) -> List[Dict[str, Any]]:
    import pyarrow.parquet as pq

    if not parquet_path.exists():
        return []
    return [dict(item) for item in pq.read_table(parquet_path).to_pylist()]


def _build_merge_row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    merge_values = tuple(str(row.get(field) or "").strip() for field in _MERGE_KEY_FIELDS)
    if any(merge_values):
        return ("promotion", *merge_values)
    return ("row", json.dumps(dict(row), sort_keys=True, ensure_ascii=True, default=str))


def _merge_row_sets(existing_rows: List[Dict[str, Any]], new_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[tuple[str, ...], Dict[str, Any]] = {}
    ordered_keys: List[tuple[str, ...]] = []

    for row in existing_rows + new_rows:
        row_key = _build_merge_row_key(row)
        if row_key not in merged:
            ordered_keys.append(row_key)
        merged[row_key] = dict(row)

    return [merged[key] for key in ordered_keys]


def _write_rows_to_parquet(rows: List[Dict[str, Any]], output_path: Path) -> Dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(_normalize_rows_for_table(rows))
    pq.write_table(table, output_path, compression="snappy")
    return {
        "status": "success",
        "output_path": str(output_path),
        "records_count": len(rows),
        "file_size_bytes": output_path.stat().st_size,
        "format": "parquet",
    }


def load_recovery_manifest(manifest_path: str | Path) -> Dict[str, Any]:
    path = Path(manifest_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["manifest_path"] = str(path)
    payload["manifest_directory"] = str(path.parent)
    return payload


def build_recovery_manifest_promotion_row(
    manifest: Mapping[str, Any] | str | Path,
) -> Dict[str, Any]:
    payload = load_recovery_manifest(manifest) if isinstance(manifest, (str, Path)) else dict(manifest)
    manifest_path = Path(str(payload.get("manifest_path") or "")).expanduser().resolve() if payload.get("manifest_path") else None
    manifest_directory = manifest_path.parent if manifest_path is not None else Path(str(payload.get("manifest_directory") or "")).expanduser().resolve()

    corpus_key = str(payload.get("corpus_key") or "").strip().lower()
    state_code = str(payload.get("state_code") or "").strip().upper()
    corpus = get_canonical_legal_corpus(corpus_key) if corpus_key else None
    preferred_state_code = state_code if corpus_key in {"state_laws", "state_admin_rules", "state_court_rules"} else None
    preferred_parquet_names = corpus.preferred_parquet_names(preferred_state_code) if corpus is not None else []
    target_filename = (
        corpus.state_parquet_filename(preferred_state_code)
        if corpus is not None and preferred_state_code
        else (corpus.combined_parquet_filename if corpus is not None else "")
    )
    target_parquet_path = (
        f"{corpus.parquet_dir_name.strip('/')}/{target_filename}"
        if corpus is not None and corpus.parquet_dir_name.strip("/")
        else target_filename
    )
    target_local_parquet_path = str(corpus.parquet_dir() / target_filename) if corpus is not None and target_filename else ""

    candidates = [dict(item) for item in list(payload.get("candidates") or [])]
    archived_sources = [dict(item) for item in list(payload.get("archived_sources") or [])]
    primary_candidate = dict(candidates[0]) if candidates else {}
    archived_success_urls = [
        str(item.get("url") or "")
        for item in archived_sources
        if bool(item.get("success")) and str(item.get("url") or "").strip()
    ]
    candidate_urls = [str(item.get("url") or "") for item in candidates if str(item.get("url") or "").strip()]
    promotion_output_dir = manifest_directory / "canonical_promotion"

    return {
        "source_type": "legal_source_recovery_manifest",
        "corpus_key": corpus_key,
        "hf_dataset_id": str(payload.get("hf_dataset_id") or (corpus.hf_dataset_id if corpus is not None else "")),
        "citation_text": str(payload.get("citation_text") or ""),
        "normalized_citation": str(payload.get("normalized_citation") or payload.get("citation_text") or ""),
        "state_code": state_code,
        "search_query": str(payload.get("search_query") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "candidate_count": len(candidates),
        "archived_count": sum(1 for item in archived_sources if bool(item.get("success"))),
        "primary_candidate_url": str(primary_candidate.get("url") or ""),
        "primary_candidate_title": str(primary_candidate.get("title") or ""),
        "primary_candidate_source": str(primary_candidate.get("source") or ""),
        "primary_candidate_source_type": str(primary_candidate.get("source_type") or ""),
        "primary_candidate_score": int(primary_candidate.get("score") or 0),
        "candidate_urls": candidate_urls,
        "archived_source_urls": archived_success_urls,
        "manifest_path": str(manifest_path) if manifest_path is not None else str(payload.get("manifest_path") or ""),
        "manifest_directory": str(manifest_directory),
        "promotion_output_dir": str(promotion_output_dir),
        "promotion_json_path": str(promotion_output_dir / "promotion_rows.json"),
        "promotion_parquet_path": str(promotion_output_dir / "promotion_rows.parquet"),
        "target_parquet_path": target_parquet_path,
        "target_local_parquet_path": target_local_parquet_path,
        "target_parquet_file": target_filename,
        "preferred_parquet_names": preferred_parquet_names,
        "cid_field": corpus.cid_field if corpus is not None else "",
        "state_field": corpus.state_field if corpus is not None else "",
    }


def promote_recovery_manifest_to_canonical_bundle(
    manifest_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    write_parquet: bool = True,
) -> Dict[str, Any]:
    payload = load_recovery_manifest(manifest_path)
    row = build_recovery_manifest_promotion_row(payload)
    promotion_dir = Path(output_dir).expanduser().resolve() if output_dir else Path(str(row.get("promotion_output_dir") or "")).expanduser().resolve()
    promotion_dir.mkdir(parents=True, exist_ok=True)

    json_path = promotion_dir / "promotion_rows.json"
    parquet_path = promotion_dir / "promotion_rows.parquet"
    metadata_path = promotion_dir / "promotion_metadata.json"
    rows = [
        {
            **row,
            "promotion_output_dir": str(promotion_dir),
            "promotion_json_path": str(json_path),
            "promotion_parquet_path": str(parquet_path),
        }
    ]
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")

    parquet_report: Optional[Dict[str, Any]] = None
    if write_parquet:
        parquet_report = _write_rows_to_parquet(rows, parquet_path)

    metadata = {
        "manifest_path": str(Path(manifest_path).expanduser().resolve()),
        "promotion_output_dir": str(promotion_dir),
        "row_count": len(rows),
        "corpus_key": str(row.get("corpus_key") or ""),
        "hf_dataset_id": str(row.get("hf_dataset_id") or ""),
        "target_parquet_path": str(row.get("target_parquet_path") or ""),
        "json_path": str(json_path),
        "parquet_path": str(parquet_path),
        "parquet_report": parquet_report,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "status": "success",
        "manifest_path": str(Path(manifest_path).expanduser().resolve()),
        "promotion_output_dir": str(promotion_dir),
        "row_count": len(rows),
        "rows": rows,
        "json_path": str(json_path),
        "parquet_path": str(parquet_path),
        "metadata_path": str(metadata_path),
        "parquet_report": parquet_report,
        "source": "legal_source_recovery_promotion",
    }


def merge_recovery_manifest_into_canonical_dataset(
    manifest_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    target_local_parquet_path: str | Path | None = None,
    write_promotion_parquet: bool = True,
) -> Dict[str, Any]:
    bundle = promote_recovery_manifest_to_canonical_bundle(
        manifest_path,
        output_dir=output_dir,
        write_parquet=write_promotion_parquet,
    )
    rows = [dict(item) for item in list(bundle.get("rows") or [])]
    if not rows:
        return {
            "status": "error",
            "error": "Promotion bundle did not contain any rows to merge.",
            "manifest_path": str(Path(manifest_path).expanduser().resolve()),
            "source": "legal_source_recovery_promotion_merge",
        }

    target_path_value = (
        str(target_local_parquet_path).strip()
        if target_local_parquet_path is not None and str(target_local_parquet_path).strip()
        else str(rows[0].get("target_local_parquet_path") or "").strip()
    )
    if not target_path_value:
        return {
            "status": "error",
            "error": "Target local parquet path is not available for the recovery manifest corpus.",
            "manifest_path": str(Path(manifest_path).expanduser().resolve()),
            "promotion_output_dir": str(bundle.get("promotion_output_dir") or ""),
            "source": "legal_source_recovery_promotion_merge",
        }

    target_path = Path(target_path_value).expanduser().resolve()
    existing_rows = _read_rows_from_parquet(target_path)
    merged_rows = _merge_row_sets(existing_rows, rows)
    parquet_report = _write_rows_to_parquet(merged_rows, target_path)
    merge_report_path = Path(str(bundle.get("promotion_output_dir") or target_path.parent)).expanduser().resolve() / "canonical_merge_report.json"
    merge_report = {
        "status": "success",
        "manifest_path": str(Path(manifest_path).expanduser().resolve()),
        "promotion_output_dir": str(bundle.get("promotion_output_dir") or ""),
        "target_local_parquet_path": str(target_path),
        "target_parquet_path": str(rows[0].get("target_parquet_path") or ""),
        "existing_row_count": len(existing_rows),
        "incoming_row_count": len(rows),
        "merged_row_count": len(merged_rows),
        "deduplicated_count": len(existing_rows) + len(rows) - len(merged_rows),
        "parquet_report": parquet_report,
        "merge_report_path": str(merge_report_path),
        "source": "legal_source_recovery_promotion_merge",
    }
    merge_report_path.write_text(json.dumps(merge_report, indent=2, sort_keys=True), encoding="utf-8")
    return merge_report


def build_recovery_manifest_release_plan(
    manifest: Mapping[str, Any] | str | Path,
    *,
    output_dir: str | Path | None = None,
    workspace_root: str | Path | None = None,
    python_bin: str = "python3",
) -> Dict[str, Any]:
    payload = load_recovery_manifest(manifest) if isinstance(manifest, (str, Path)) else dict(manifest)
    row = build_recovery_manifest_promotion_row(payload)
    manifest_path_obj = Path(str(payload.get("manifest_path") or "recovery_manifest.json")).expanduser().resolve()
    promotion_dir = Path(output_dir).expanduser().resolve() if output_dir else Path(str(row.get("promotion_output_dir") or "")).expanduser().resolve()
    workspace_root_path = Path(workspace_root).expanduser().resolve() if workspace_root else Path.cwd().resolve()
    python_bin_quoted = shlex.quote(str(python_bin or "python3"))
    promote_command = (
        f"cd {shlex.quote(str(workspace_root_path))} && "
        f"PYTHONPATH=src {python_bin_quoted} -c "
        f"\"from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery_promotion import "
        f"promote_recovery_manifest_to_canonical_bundle as _promote; "
        f"_promote({str(manifest_path_obj)!r}, output_dir={str(promotion_dir)!r})\""
    )
    merge_command = (
        f"cd {shlex.quote(str(workspace_root_path))} && "
        f"PYTHONPATH=src {python_bin_quoted} -c "
        f"\"from ipfs_datasets_py.processors.legal_scrapers.legal_source_recovery_promotion import "
        f"merge_recovery_manifest_into_canonical_dataset as _merge; "
        f"_merge({str(manifest_path_obj)!r}, output_dir={str(promotion_dir)!r})\""
    )
    has_target_parquet = bool(str(row.get("target_local_parquet_path") or "").strip())

    commands = [
        {
            "stage": "promote_bundle",
            "command": promote_command,
            "status": "ready",
        },
        {
            "stage": "merge_into_canonical_dataset",
            "command": merge_command if has_target_parquet else None,
            "status": "ready" if has_target_parquet else "blocked",
            "reason": None if has_target_parquet else "Target canonical parquet path is not available for the recovery manifest corpus.",
            "target_parquet_path": str(row.get("target_parquet_path") or ""),
            "target_local_parquet_path": str(row.get("target_local_parquet_path") or ""),
        },
    ]

    return {
        "status": "planned",
        "preview": True,
        "corpus": str(row.get("corpus_key") or ""),
        "workspace_root": str(workspace_root_path),
        "artifacts": {
            "manifest_path": str(manifest_path_obj),
            "promotion_output_dir": str(promotion_dir),
            "promotion_json_path": str(promotion_dir / "promotion_rows.json"),
            "promotion_parquet_path": str(promotion_dir / "promotion_rows.parquet"),
            "merge_report_path": str(promotion_dir / "canonical_merge_report.json"),
            "target_parquet_path": str(row.get("target_parquet_path") or ""),
            "target_local_parquet_path": str(row.get("target_local_parquet_path") or ""),
            "hf_dataset_id": str(row.get("hf_dataset_id") or ""),
        },
        "commands": commands,
        "source": "legal_source_recovery_promotion_release_plan",
    }


__all__ = [
    "build_recovery_manifest_promotion_row",
    "build_recovery_manifest_release_plan",
    "load_recovery_manifest",
    "merge_recovery_manifest_into_canonical_dataset",
    "promote_recovery_manifest_to_canonical_bundle",
]