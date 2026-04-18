#!/usr/bin/env python3
"""Refresh the canonical state-laws corpus and publish merged HF artifacts.

The state-specific scrapers write one JSON-LD file per state. This command
turns those JSON-LD files into canonical CID-keyed parquet shards, optionally
merges already-published Hugging Face rows, and uploads the refreshed shards
back to the canonical JusticeDAO state-laws dataset.
"""

from __future__ import annotations

import argparse
import asyncio
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

from ipfs_datasets_py.processors.legal_data.canonical_legal_corpora import (
    get_canonical_legal_corpus,
)
from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (
    _resolve_hf_token,
)
from ipfs_datasets_py.processors.legal_scrapers.state_laws_scraper import (
    US_STATES,
    scrape_state_laws,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_obj
from ipfs_datasets_py.utils.cid_utils import canonical_json_bytes


STATE_CODES_50: List[str] = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

_CORPUS = get_canonical_legal_corpus("state_laws")


def _normalize_states(value: str, *, include_dc: bool = False) -> List[str]:
    raw = str(value or "all").strip()
    if not raw or raw.lower() == "all":
        states = list(STATE_CODES_50)
        if include_dc:
            states.append("DC")
        return states

    states: List[str] = []
    for item in raw.split(","):
        code = item.strip().upper()
        if not code:
            continue
        if code not in US_STATES:
            raise ValueError(f"Unknown state code: {code}")
        if code == "DC" and not include_dc:
            raise ValueError("DC requested but --include-dc was not set")
        states.append(code)

    deduped: List[str] = []
    seen = set()
    for state in states:
        if state not in seen:
            deduped.append(state)
            seen.add(state)
    return deduped


def _coerce_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _first_text(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _safe_cid_for_obj(payload: Mapping[str, Any]) -> str:
    try:
        return cid_for_obj(dict(payload))
    except Exception:
        digest = hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()
        return f"sha256:{digest}"


def jsonld_payload_to_canonical_row(payload: Mapping[str, Any], *, state_code: str) -> Dict[str, Any]:
    """Convert one state-law JSON-LD object into the canonical parquet schema."""
    state = str(state_code or payload.get("stateCode") or payload.get("state_code") or "").strip().upper()
    identifier = _first_text(
        payload,
        ("identifier", "legislationIdentifier", "sectionNumber", "source_id", "@id"),
    )
    name = _first_text(payload, ("name", "sectionName", "title", "description"))
    text = _first_text(payload, ("text", "articleBody", "description"))
    source_url = _first_text(payload, ("sourceUrl", "url", "sameAs"))
    source_id = _first_text(payload, ("@id", "source_id")) or identifier or source_url

    row_without_cid = {
        "state_code": state,
        "source_id": source_id,
        "identifier": identifier,
        "name": name,
        "text": text,
        "source_url": source_url,
        "jsonld": json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
        "legislation_type": _first_text(payload, ("legislationType", "@type")),
        "legislation_jurisdiction": _first_text(payload, ("legislationJurisdiction",)),
    }
    return {
        "ipfs_cid": _safe_cid_for_obj(row_without_cid),
        **row_without_cid,
    }


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    for field in ("ipfs_cid", "source_id", "identifier", "source_url"):
        value = str(row.get(field) or "").strip()
        if value:
            return (field, value)
    return ("row", json.dumps(dict(row), ensure_ascii=True, sort_keys=True, default=str))


def merge_canonical_rows(existing_rows: Sequence[Mapping[str, Any]], new_rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Merge rows by stable identity, preferring the refreshed scraped row."""
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
    return [{field: row.get(field) for field in fields} for row in rows]


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


def _iter_jsonld_payloads(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
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


def build_state_laws_parquet_artifacts(
    *,
    states: Sequence[str],
    jsonld_dir: Path,
    parquet_dir: Path,
    merge_existing_local: bool = True,
    merge_hf_existing: bool = False,
    repo_id: str = _CORPUS.hf_dataset_id,
    token: Optional[str] = None,
    hf_cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build per-state and combined parquet files from state-law JSON-LD."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    hf_cache_dir = hf_cache_dir or (Path.home() / ".cache" / "state_laws_hf_merge")
    repo_files: Optional[set[str]] = None

    if merge_hf_existing:
        try:
            from huggingface_hub import HfApi

            repo_files = set(HfApi(token=token).list_repo_files(repo_id=repo_id, repo_type="dataset"))
        except Exception:
            repo_files = set()

    state_reports: List[Dict[str, Any]] = []
    combined_rows: List[Dict[str, Any]] = []
    missing_jsonld: List[str] = []

    for state in states:
        state_jsonld_path = jsonld_dir / f"STATE-{state}.jsonld"
        if not state_jsonld_path.exists():
            missing_jsonld.append(state)
            new_rows: List[Dict[str, Any]] = []
        else:
            new_rows = [
                jsonld_payload_to_canonical_row(payload, state_code=state)
                for payload in _iter_jsonld_payloads(state_jsonld_path)
            ]

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

        merged_rows = merge_canonical_rows(existing_rows, new_rows)
        if merged_rows:
            _write_parquet_rows(merged_rows, state_parquet_path)
        combined_rows.extend(merged_rows)
        state_reports.append(
            {
                "state": state,
                "jsonld_path": str(state_jsonld_path),
                "parquet_path": str(state_parquet_path),
                "scraped_row_count": len(new_rows),
                "existing_row_count": len(existing_rows),
                "merged_row_count": len(merged_rows),
                "jsonld_exists": state_jsonld_path.exists(),
            }
        )

    combined_rows = merge_canonical_rows([], combined_rows)
    combined_path = parquet_dir / _CORPUS.combined_parquet_filename
    if combined_rows:
        _write_parquet_rows(combined_rows, combined_path)

    manifest = {
        "status": "success",
        "corpus_key": _CORPUS.key,
        "repo_id": repo_id,
        "states": list(states),
        "state_count": len(states),
        "missing_jsonld_states": missing_jsonld,
        "parquet_dir": str(parquet_dir),
        "combined_parquet_path": str(combined_path),
        "combined_row_count": len(combined_rows),
        "merge_existing_local": bool(merge_existing_local),
        "merge_hf_existing": bool(merge_hf_existing),
        "state_reports": state_reports,
    }
    manifest_path = parquet_dir / "state_laws_refresh_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


def _publish_parquet_dir(
    *,
    parquet_dir: Path,
    repo_id: str,
    token: Optional[str],
    create_repo: bool,
    verify: bool,
    commit_message: str,
) -> Dict[str, Any]:
    from scripts.repair.publish_parquet_to_hf import publish

    return publish(
        local_dir=parquet_dir,
        repo_id=repo_id,
        commit_message=commit_message,
        create_repo=create_repo,
        token=token,
        path_in_repo=_CORPUS.parquet_dir_name,
        allow_patterns=["*.parquet", "*.json", "*.md"],
        do_verify=verify,
        cid_column=_CORPUS.cid_field,
    )


async def refresh_state_laws_corpus(args: argparse.Namespace) -> Dict[str, Any]:
    states = _normalize_states(args.states, include_dc=bool(args.include_dc))
    output_root = Path(args.output_root).expanduser().resolve() if args.output_root else _CORPUS.default_local_root()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve() if args.jsonld_dir else _CORPUS.jsonld_dir(str(output_root))
    parquet_dir = Path(args.parquet_dir).expanduser().resolve() if args.parquet_dir else _CORPUS.parquet_dir(str(output_root))
    repo_id = str(args.repo_id or _CORPUS.hf_dataset_id).strip()
    needs_hf_token = bool(args.merge_hf_existing or args.publish_to_hf or args.verify)
    hf_token = (
        _resolve_hf_token(str(args.hf_token or "").strip() or None)
        if needs_hf_token
        else (str(args.hf_token or "").strip() or None)
    )

    plan = {
        "states": states,
        "state_count": len(states),
        "scrape": bool(args.scrape),
        "jsonld_dir": str(jsonld_dir),
        "parquet_dir": str(parquet_dir),
        "repo_id": repo_id,
        "publish_to_hf": bool(args.publish_to_hf),
        "merge_hf_existing": bool(args.merge_hf_existing),
    }
    if args.dry_run:
        return {"status": "dry_run", "plan": plan}

    scrape_result: Dict[str, Any] | None = None
    if args.scrape:
        scrape_result = await scrape_state_laws(
            states=states,
            legal_areas=None,
            output_format="json",
            include_metadata=True,
            rate_limit_delay=float(args.rate_limit_delay),
            max_statutes=int(args.max_statutes) if int(args.max_statutes or 0) > 0 else None,
            use_state_specific_scrapers=True,
            allow_justia_fallback=bool(args.allow_justia_fallback),
            output_dir=str(output_root),
            write_jsonld=True,
            strict_full_text=bool(args.strict_full_text),
            min_full_text_chars=int(args.min_full_text_chars),
            hydrate_statute_text=not bool(args.no_hydrate_statute_text),
            parallel_workers=int(args.parallel_workers),
            per_state_retry_attempts=int(args.per_state_retry_attempts),
            retry_zero_statute_states=True,
            per_state_timeout_seconds=float(args.per_state_timeout_seconds),
        )

    build_result = build_state_laws_parquet_artifacts(
        states=states,
        jsonld_dir=jsonld_dir,
        parquet_dir=parquet_dir,
        merge_existing_local=not bool(args.no_merge_existing_local),
        merge_hf_existing=bool(args.merge_hf_existing),
        repo_id=repo_id,
        token=hf_token,
    )

    scrape_gaps = []
    if isinstance(scrape_result, dict):
        metadata = scrape_result.get("metadata") or {}
        coverage = metadata.get("coverage_summary") or {}
        scrape_gaps = list(coverage.get("coverage_gap_states") or [])
    build_gaps = list(build_result.get("missing_jsonld_states") or [])
    is_complete = not scrape_gaps and not build_gaps

    if args.publish_to_hf and not is_complete and not bool(args.allow_incomplete_publish):
        return {
            "status": "error",
            "error": "Refusing to publish incomplete state-laws corpus refresh without --allow-incomplete-publish.",
            "plan": plan,
            "scrape": scrape_result,
            "build": build_result,
            "publish": None,
            "scrape_gap_states": scrape_gaps,
            "build_gap_states": build_gaps,
        }

    publish_result: Dict[str, Any] | None = None
    if args.publish_to_hf:
        publish_result = _publish_parquet_dir(
            parquet_dir=parquet_dir,
            repo_id=repo_id,
            token=hf_token,
            create_repo=bool(args.create_repo),
            verify=bool(args.verify),
            commit_message=str(args.commit_message or "Refresh canonical state laws corpus"),
        )

    return {
        "status": "success" if is_complete else "partial_success",
        "plan": plan,
        "scrape": scrape_result,
        "build": build_result,
        "publish": publish_result,
        "scrape_gap_states": scrape_gaps,
        "build_gap_states": build_gaps,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh and publish the canonical state-laws corpus")
    parser.add_argument("--states", default="all", help="Comma-separated state codes, or all")
    parser.add_argument("--include-dc", action="store_true", help="Include District of Columbia when --states=all")
    parser.add_argument("--output-root", default="", help="Corpus output root; defaults to ~/.ipfs_datasets/state_laws")
    parser.add_argument("--jsonld-dir", default="", help="Override source JSON-LD directory")
    parser.add_argument("--parquet-dir", default="", help="Override destination parquet directory")
    parser.add_argument("--scrape", action="store_true", help="Run state scrapers before building parquet")
    parser.add_argument("--max-statutes", type=int, default=0, help="Optional cap across the scrape run; 0 means all")
    parser.add_argument("--rate-limit-delay", type=float, default=1.0)
    parser.add_argument("--parallel-workers", type=int, default=4)
    parser.add_argument("--per-state-retry-attempts", type=int, default=1)
    parser.add_argument("--per-state-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--strict-full-text", action="store_true")
    parser.add_argument("--min-full-text-chars", type=int, default=300)
    parser.add_argument("--no-hydrate-statute-text", action="store_true")
    parser.add_argument("--allow-justia-fallback", action="store_true")
    parser.add_argument("--no-merge-existing-local", action="store_true")
    parser.add_argument("--merge-hf-existing", action="store_true", help="Download and merge existing HF state parquet shards")
    parser.add_argument("--publish-to-hf", action="store_true")
    parser.add_argument("--allow-incomplete-publish", action="store_true")
    parser.add_argument("--repo-id", default=_CORPUS.hf_dataset_id)
    parser.add_argument("--hf-token", default="")
    parser.add_argument("--create-repo", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--commit-message", default="Refresh canonical state laws corpus")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(refresh_state_laws_corpus(args))
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Status: {result.get('status')}")
        plan = result.get("plan") or {}
        print(f"States: {plan.get('state_count')} ({','.join(plan.get('states') or [])})")
        print(f"JSON-LD: {plan.get('jsonld_dir')}")
        print(f"Parquet: {plan.get('parquet_dir')}")
        build = result.get("build") or {}
        if build:
            print(f"Combined rows: {build.get('combined_row_count')}")
            print(f"Missing JSON-LD states: {','.join(build.get('missing_jsonld_states') or []) or 'None'}")
        if result.get("publish"):
            print(f"Publish: {(result.get('publish') or {}).get('upload_commit')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
