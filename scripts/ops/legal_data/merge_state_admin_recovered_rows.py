#!/usr/bin/env python3
"""Merge daemon-recovered state administrative rule rows into canonical parquets.

The agentic scraper daemon writes recovered rows under ``recovered_rows`` so a
long-running scrape can hand off partial wins to a later merge/publish job. This
command turns those row artifacts into the canonical JusticeDAO admin-rules
parquet layout without requiring a full JSON-LD rebuild.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import (  # noqa: E402
    get_canonical_legal_corpus,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (  # noqa: E402
    _resolve_hf_token,
)
from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes, cid_for_obj  # noqa: E402


_CORPUS = get_canonical_legal_corpus("state_admin_rules")


def _first_text(row: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return ""


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _safe_cid_for_obj(payload: Mapping[str, Any]) -> str:
    try:
        return cid_for_obj(dict(payload))
    except Exception:
        digest = hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()
        return f"sha256:{digest}"


def recovered_admin_row_to_canonical_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert one recovered admin-rule row into the canonical parquet schema."""
    state = _first_text(row, ("state_code", "state", "jurisdiction")).upper()
    identifier = _first_text(
        row,
        (
            "identifier",
            "section_number",
            "sectionNumber",
            "citation",
            "rule_number",
            "ruleNumber",
            "source_id",
        ),
    )
    name = _first_text(row, ("name", "title", "section_name", "sectionName", "heading"))
    text = _first_text(row, ("text", "full_text", "fullText", "content", "body"))
    source_url = _first_text(row, ("source_url", "sourceUrl", "url", "primary_candidate_url"))
    source_id = _first_text(row, ("source_id", "@id", "id")) or source_url or identifier
    structured_data = row.get("structured_data")
    jsonld_source = structured_data if isinstance(structured_data, Mapping) else row

    row_without_cid: Dict[str, Any] = {
        "state_code": state,
        "source_id": source_id,
        "identifier": identifier,
        "name": name,
        "text": text,
        "source_url": source_url,
        "jsonld": _json_text(jsonld_source),
        "legislation_type": _first_text(row, ("legislation_type", "legislationType", "@type")) or "AdministrativeRule",
        "legislation_jurisdiction": _first_text(row, ("legislation_jurisdiction", "legislationJurisdiction")) or state,
        "agency": _first_text(row, ("agency", "agency_name", "agencyName")),
        "chapter": _first_text(row, ("chapter", "chapter_number", "chapterNumber")),
        "title_number": _first_text(row, ("title_number", "titleNumber")),
        "method_used": _first_text(row, ("method_used", "methodUsed")),
        "recovered_by": _first_text(row, ("recovered_by",)),
        "recovered_at": _first_text(row, ("recovered_at",)),
    }
    row_without_cid = {key: value for key, value in row_without_cid.items() if value not in ("", None)}
    return {
        "ipfs_cid": _safe_cid_for_obj(row_without_cid),
        **row_without_cid,
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    state = str(row.get("state_code") or "").strip().upper()
    source_id = str(row.get("source_id") or "").strip()
    identifier = str(row.get("identifier") or "").strip()
    source_url = str(row.get("source_url") or "").strip()
    if state and source_id:
        return ("source_id", state, source_id)
    if state and identifier and source_url:
        return ("identifier_url", state, identifier, source_url)
    if state and source_url:
        return ("source_url", state, source_url)
    cid = str(row.get("ipfs_cid") or "").strip()
    if cid:
        return ("cid", cid)
    return ("row", json.dumps(dict(row), ensure_ascii=True, sort_keys=True, default=str))


def merge_canonical_rows(
    existing_rows: Sequence[Mapping[str, Any]],
    new_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Merge rows by stable identity, preferring newly recovered rows."""
    merged: Dict[tuple[str, ...], Dict[str, Any]] = {}
    order: List[tuple[str, ...]] = []
    for row in list(existing_rows) + list(new_rows):
        normalized = dict(row)
        key = _row_key(normalized)
        if key not in merged:
            order.append(key)
        merged[key] = normalized
    return [merged[key] for key in order]


def _normalize_rows_for_parquet(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    if not rows:
        return [{"_empty": True}]
    fields: List[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fields.append(key)
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                field: (
                    json.dumps(row.get(field), ensure_ascii=False, sort_keys=True)
                    if isinstance(row.get(field), (dict, list))
                    else row.get(field)
                )
                for field in fields
            }
        )
    return normalized


def _read_parquet_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    import pyarrow.parquet as pq

    return [dict(row) for row in pq.read_table(path).to_pylist()]


def _write_parquet_rows(rows: Sequence[Mapping[str, Any]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(_normalize_rows_for_parquet(rows)), path, compression="snappy")


def _iter_jsonl_rows(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                yield payload


def discover_recovered_row_files(paths: Sequence[str | Path]) -> List[Path]:
    """Resolve explicit JSONL files, manifests, or daemon output directories."""
    discovered: List[Path] = []
    seen = set()

    def add(path: Path) -> None:
        resolved = path.expanduser().resolve()
        if resolved.is_file() and resolved.suffix == ".jsonl" and resolved not in seen:
            discovered.append(resolved)
            seen.add(resolved)

    for value in paths:
        path = Path(value).expanduser()
        if path.is_file() and path.suffix == ".jsonl":
            add(path)
            continue
        if path.is_file() and path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                payload = {}
            candidate = str(payload.get("statutes_jsonl_path") or "").strip() if isinstance(payload, dict) else ""
            if candidate:
                add(Path(candidate))
            continue
        if path.is_dir():
            for manifest_path in sorted(path.rglob("*_manifest.json")):
                try:
                    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    payload = {}
                candidate = str(payload.get("statutes_jsonl_path") or "").strip() if isinstance(payload, dict) else ""
                if candidate:
                    add(Path(candidate))
            for jsonl_path in sorted(path.rglob("*_statutes.jsonl")):
                add(jsonl_path)

    return discovered


def load_recovered_admin_rows(paths: Sequence[str | Path]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in discover_recovered_row_files(paths):
        rows.extend(recovered_admin_row_to_canonical_row(row) for row in _iter_jsonl_rows(path))
    return rows


def _download_existing_hf_state_parquet(
    *,
    repo_id: str,
    state_code: str,
    token: Optional[str],
    cache_dir: Path,
    repo_files: Optional[set[str]] = None,
) -> Path | None:
    remote_path = f"{_CORPUS.parquet_dir_name}/{_CORPUS.state_parquet_filename(state_code)}"
    if repo_files is not None and remote_path not in repo_files:
        return None
    try:
        from huggingface_hub import hf_hub_download
    except Exception:
        return None
    try:
        downloaded = hf_hub_download(
            repo_id=repo_id,
            repo_type="dataset",
            filename=remote_path,
            token=token,
            cache_dir=str(cache_dir),
        )
    except Exception:
        return None
    return Path(downloaded)


def _publish_parquet_dir(
    *,
    parquet_dir: Path,
    repo_id: str,
    token: Optional[str],
    commit_message: str,
) -> Dict[str, Any]:
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    upload_info = api.upload_folder(
        folder_path=str(parquet_dir),
        repo_id=repo_id,
        repo_type="dataset",
        path_in_repo=_CORPUS.parquet_dir_name,
        commit_message=commit_message,
        allow_patterns=["*.parquet", "*.json"],
    )
    return {
        "status": "success",
        "repo_id": repo_id,
        "path_in_repo": _CORPUS.parquet_dir_name,
        "local_path": str(parquet_dir),
        "upload_commit": str(upload_info),
    }


def build_state_admin_recovered_parquet_artifacts(
    *,
    input_paths: Sequence[str | Path],
    parquet_dir: Path,
    merge_existing_local: bool = True,
    merge_hf_existing: bool = False,
    repo_id: str = _CORPUS.hf_dataset_id,
    token: Optional[str] = None,
    hf_cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    parquet_dir.mkdir(parents=True, exist_ok=True)
    hf_cache_dir = hf_cache_dir or (Path.home() / ".cache" / "state_admin_rules_hf_merge")
    recovered_rows = load_recovered_admin_rows(input_paths)

    rows_by_state: Dict[str, List[Dict[str, Any]]] = {}
    for row in recovered_rows:
        state = str(row.get("state_code") or "").strip().upper()
        if not state:
            continue
        rows_by_state.setdefault(state, []).append(row)

    repo_files: Optional[set[str]] = None
    if merge_hf_existing:
        try:
            from huggingface_hub import HfApi

            repo_files = set(HfApi(token=token).list_repo_files(repo_id=repo_id, repo_type="dataset"))
        except Exception:
            repo_files = set()

    state_reports: List[Dict[str, Any]] = []
    combined_rows: List[Dict[str, Any]] = []
    for state in sorted(rows_by_state):
        state_parquet_path = parquet_dir / _CORPUS.state_parquet_filename(state)
        existing_rows: List[Dict[str, Any]] = []
        if merge_hf_existing:
            remote_path = _download_existing_hf_state_parquet(
                repo_id=repo_id,
                state_code=state,
                token=token,
                cache_dir=hf_cache_dir,
                repo_files=repo_files,
            )
            if remote_path is not None:
                existing_rows.extend(_read_parquet_rows(remote_path))
        if merge_existing_local:
            existing_rows.extend(_read_parquet_rows(state_parquet_path))

        new_rows = merge_canonical_rows([], rows_by_state[state])
        merged_rows = merge_canonical_rows(existing_rows, new_rows)
        _write_parquet_rows(merged_rows, state_parquet_path)
        combined_rows.extend(merged_rows)
        state_reports.append(
            {
                "state": state,
                "parquet_path": str(state_parquet_path),
                "target_hf_parquet_path": f"{_CORPUS.parquet_dir_name}/{_CORPUS.state_parquet_filename(state)}",
                "recovered_row_count": len(rows_by_state[state]),
                "deduplicated_recovered_row_count": len(new_rows),
                "existing_row_count": len(existing_rows),
                "merged_row_count": len(merged_rows),
            }
        )

    combined_rows = merge_canonical_rows([], combined_rows)
    combined_path = parquet_dir / _CORPUS.combined_parquet_filename
    if combined_rows:
        _write_parquet_rows(combined_rows, combined_path)

    manifest = {
        "status": "success" if recovered_rows else "empty",
        "corpus_key": _CORPUS.key,
        "repo_id": repo_id,
        "input_paths": [str(Path(path).expanduser()) for path in input_paths],
        "discovered_jsonl_paths": [str(path) for path in discover_recovered_row_files(input_paths)],
        "states": sorted(rows_by_state),
        "state_count": len(rows_by_state),
        "recovered_row_count": len(recovered_rows),
        "parquet_dir": str(parquet_dir),
        "target_hf_parquet_dir": _CORPUS.parquet_dir_name,
        "combined_parquet_path": str(combined_path),
        "target_hf_combined_parquet_path": _CORPUS.combined_parquet_path(),
        "combined_row_count": len(combined_rows),
        "merge_existing_local": bool(merge_existing_local),
        "merge_hf_existing": bool(merge_hf_existing),
        "state_reports": state_reports,
    }
    manifest_path = parquet_dir / "state_admin_recovered_rows_merge_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge daemon-recovered state admin rule rows into canonical parquet shards."
    )
    parser.add_argument("inputs", nargs="+", help="Recovered row JSONL files, manifests, or daemon output directories.")
    parser.add_argument("--output-dir", required=True, help="Output root for upload-ready artifacts.")
    parser.add_argument("--parquet-dir", default="", help="Override destination parquet directory.")
    parser.add_argument("--no-merge-existing-local", action="store_true")
    parser.add_argument("--merge-hf-existing", action="store_true", help="Download and merge existing HF state parquet shards.")
    parser.add_argument("--repo-id", default=_CORPUS.hf_dataset_id)
    parser.add_argument("--hf-token", default="")
    parser.add_argument("--hf-cache-dir", default="")
    parser.add_argument("--publish-to-hf", action="store_true", help="Upload merged parquet artifacts to Hugging Face.")
    parser.add_argument("--commit-message", default="Merge recovered state administrative rule rows")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    parquet_dir = (
        Path(args.parquet_dir).expanduser().resolve()
        if args.parquet_dir
        else output_dir / _CORPUS.parquet_dir_name
    )
    token = _resolve_hf_token(str(args.hf_token or "").strip() or None) if (args.merge_hf_existing or args.publish_to_hf) else None

    build = build_state_admin_recovered_parquet_artifacts(
        input_paths=args.inputs,
        parquet_dir=parquet_dir,
        merge_existing_local=not bool(args.no_merge_existing_local),
        merge_hf_existing=bool(args.merge_hf_existing),
        repo_id=str(args.repo_id or _CORPUS.hf_dataset_id),
        token=token,
        hf_cache_dir=Path(args.hf_cache_dir).expanduser().resolve() if args.hf_cache_dir else None,
    )
    publish = None
    if args.publish_to_hf:
        publish = _publish_parquet_dir(
            parquet_dir=parquet_dir,
            repo_id=str(args.repo_id or _CORPUS.hf_dataset_id),
            token=token,
            commit_message=str(args.commit_message or "Merge recovered state administrative rule rows"),
        )

    report = {
        "status": build.get("status"),
        "build": build,
        "publish": publish,
    }
    report_path = output_dir / "state_admin_recovered_rows_merge_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["report_path"] = str(report_path)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Status: {report.get('status')}")
        print(f"States: {build.get('states')}")
        print(f"Recovered rows: {build.get('recovered_row_count')}")
        print(f"Combined parquet: {build.get('combined_parquet_path')}")
        print(f"Report: {report_path}")

    return 0 if str(report.get("status") or "") in {"success", "empty"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
