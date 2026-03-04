#!/usr/bin/env python3
"""Smoke-check Oregon Administrative Rules dataset quality.

Validates local artifacts or remotely published Hugging Face parquet files.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from datasets import load_dataset
from huggingface_hub import hf_hub_url, list_repo_files


OAR_RULE_RE = re.compile(r"\b\d{3}-\d{3}-\d{4}\b")


def _default_local_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "state_administrative_rules" / "OR" / "parsed"


def _validate_records(records: List[Dict[str, Any]], source: str) -> Dict[str, Any]:
    required = ["state_code", "statute_id", "section_number", "full_text", "source_url"]
    missing_required = {key: 0 for key in required}
    with_oar_cite = 0
    with_jsonld = 0

    for row in records:
        for key in required:
            value = row.get(key)
            if value is None or str(value).strip() == "":
                missing_required[key] += 1

        statute_id = str(row.get("statute_id") or "")
        section_number = str(row.get("section_number") or "")
        if OAR_RULE_RE.search(statute_id) or OAR_RULE_RE.search(section_number):
            with_oar_cite += 1

        structured_data = row.get("structured_data")
        if isinstance(structured_data, dict) and isinstance(structured_data.get("jsonld"), dict):
            with_jsonld += 1

    count = len(records)
    failure_reasons: List[str] = []
    if count == 0:
        failure_reasons.append("no_records")
    if count > 0 and with_oar_cite == 0:
        failure_reasons.append("no_oar_citations_detected")

    for key, misses in missing_required.items():
        if count > 0 and misses == count:
            failure_reasons.append(f"missing_column:{key}")

    status = "success" if not failure_reasons else "error"
    return {
        "status": status,
        "source": source,
        "record_count": count,
        "with_oar_citation": with_oar_cite,
        "with_jsonld": with_jsonld,
        "missing_required": missing_required,
        "failure_reasons": failure_reasons,
    }


def _load_local_records(local_dir: Path, max_rows: int) -> List[Dict[str, Any]]:
    parquet_path = local_dir / "oregon_administrative_rules.parquet"
    if parquet_path.exists():
        ds = load_dataset("parquet", data_files={"train": str(parquet_path)}, split=f"train[:{max_rows}]")
        return [dict(row) for row in ds]

    json_path = local_dir / "oregon_administrative_rules.json"
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        records = payload.get("records") or []
        return [dict(row) for row in records[:max_rows]]

    jsonl_path = local_dir / "oregon_administrative_rules.jsonl"
    if jsonl_path.exists():
        out: List[Dict[str, Any]] = []
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for idx, line in enumerate(handle):
                if idx >= max_rows:
                    break
                line = line.strip()
                if not line:
                    continue
                out.append(json.loads(line))
        return out

    raise FileNotFoundError(
        "No OAR dataset artifact found. Expected one of: "
        "oregon_administrative_rules.parquet/json/jsonl"
    )


def _find_remote_parquet(repo_id: str, path_prefix: str) -> str:
    files = list_repo_files(repo_id=repo_id, repo_type="dataset")
    prefix = path_prefix.strip("/")
    candidates = sorted(
        f
        for f in files
        if f.endswith(".parquet") and (f == prefix or f.startswith(prefix + "/"))
    )
    if not candidates:
        raise RuntimeError(f"No parquet files found under '{prefix}' in {repo_id}")

    for candidate in candidates:
        lowered = candidate.lower()
        if "oregon_administrative_rules" in lowered:
            return candidate
    return candidates[0]


def _load_remote_records(repo_id: str, path_prefix: str, max_rows: int) -> Dict[str, Any]:
    parquet_file = _find_remote_parquet(repo_id=repo_id, path_prefix=path_prefix)
    url = hf_hub_url(repo_id=repo_id, repo_type="dataset", filename=parquet_file)
    ds = load_dataset("parquet", data_files={"train": url}, split=f"train[:{max_rows}]")
    rows = [dict(row) for row in ds]
    return {"parquet_file": parquet_file, "records": rows}


async def _main(args: argparse.Namespace) -> int:
    if args.mode == "local":
        local_dir = Path(args.local_dir).expanduser().resolve()
        records = _load_local_records(local_dir=local_dir, max_rows=args.max_rows)
        report = _validate_records(records, source=f"local:{local_dir}")
        report["local_dir"] = str(local_dir)
    else:
        remote = _load_remote_records(repo_id=args.repo_id, path_prefix=args.path_prefix, max_rows=args.max_rows)
        report = _validate_records(remote["records"], source=f"hf:{args.repo_id}/{remote['parquet_file']}")
        report["repo_id"] = args.repo_id
        report["parquet_file"] = remote["parquet_file"]

    print(json.dumps(report))
    return 0 if report.get("status") == "success" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check Oregon Administrative Rules dataset")
    parser.add_argument("--mode", choices=["local", "hf"], default="local")
    parser.add_argument("--local-dir", default=str(_default_local_dir()))
    parser.add_argument("--repo-id", default="justicedao/ipfs_state_admin_rules")
    parser.add_argument("--path-prefix", default="OR/parsed")
    parser.add_argument("--max-rows", type=int, default=256)
    return parser.parse_args()


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(_main(parse_args())))
