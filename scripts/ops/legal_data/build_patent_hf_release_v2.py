#!/usr/bin/env python3
"""Build deterministic, privacy-reviewed JusticeDAO patent/legal HF release v2.

Default mode is **dry-run**: the builder admits public rows, verifies
orphan-free joins, materializes a multi-repo content-addressed release in
memory, and prints the plan. No local staging occurs unless ``--stage`` is
supplied, and this script never performs a remote Hub upload (no ``HfApi.upload_file`` path).

Input is a JSON array (or NDJSON) of release rows. Each row must include
record_id, config_name, classification, source_lineage, rights_review,
privacy_review, and fields (authoritative / ai_derived partitions). Private
or mixed classification batches fail before staging.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.domains.patent.hf_layout_v2 import (  # noqa: E402
    DEFAULT_VERSION_TAG,
    ORGANIZATION,
)
from ipfs_datasets_py.processors.domains.patent.hf_release_v2 import (  # noqa: E402
    CONTENT_CONFIGS,
    OrphanJoinError,
    PatentHFReleaseV2Error,
    PatentReleaseSafetyError,
    ReleaseRowV2,
    build_patent_hf_release_v2,
    validate_patent_hf_release_v2,
)
from ipfs_datasets_py.processors.domains.patent.release_policy import (  # noqa: E402
    ReleasePolicyError,
)


def _load_rows(path: Path) -> list[Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"input is empty: {path}")
    if path.suffix.lower() == ".ndjson" or (
        not text.startswith("[") and "\n" in text
    ):
        rows: list[Mapping[str, Any]] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"invalid NDJSON on line {line_no}: {exc}"
                ) from exc
            if not isinstance(value, Mapping):
                raise SystemExit(f"NDJSON line {line_no} must be an object")
            rows.append(value)
        return rows
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON input: {exc}") from exc
    if isinstance(payload, Mapping) and "records" in payload:
        payload = payload["records"]
    if not isinstance(payload, list) or not payload:
        raise SystemExit("input must be a non-empty JSON array of rows")
    rows = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise SystemExit(f"row[{index}] must be an object")
        rows.append(item)
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic privacy-reviewed JusticeDAO patent/legal "
            "v2 multi-repo release artifacts (default: dry-run, no upload)."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to JSON array or NDJSON of release rows",
    )
    parser.add_argument(
        "--organization",
        default=ORGANIZATION,
        help=f"Lowercase Hub organization (default: {ORGANIZATION})",
    )
    parser.add_argument(
        "--version-tag",
        default=DEFAULT_VERSION_TAG,
        help=f"Layout/release version tag (default: {DEFAULT_VERSION_TAG})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Local staging directory (required with --stage)",
    )
    parser.add_argument(
        "--max-rows-per-shard",
        type=int,
        default=1024,
        help="Maximum projected rows per Parquet shard",
    )
    parser.add_argument(
        "--source-root-cid",
        default="",
        help="Optional pre-bound source root CID (else computed)",
    )
    parser.add_argument(
        "--index-root-cid",
        default="",
        help="Optional pre-bound index root CID (else computed)",
    )
    parser.add_argument(
        "--evaluation-root-cid",
        default="",
        help="Optional pre-bound evaluation root CID (else empty sentinel)",
    )
    parser.add_argument(
        "--stage",
        action="store_true",
        help=(
            "Write local staged artifacts. Default is dry-run only "
            "(no filesystem staging, no remote upload)."
        ),
    )
    parser.add_argument(
        "--print-manifest",
        action="store_true",
        help="Print the release manifest JSON to stdout",
    )
    parser.add_argument(
        "--list-configs",
        action="store_true",
        help="Print supported content config names and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.list_configs:
        for name in sorted(CONTENT_CONFIGS):
            print(name)
        return 0

    # Explicit contract: this CLI has no upload path.
    if getattr(args, "upload", None) or getattr(args, "push", None):
        parser.error("remote upload is not supported by this builder")

    dry_run = not bool(args.stage)
    if not dry_run and args.output_dir is None:
        parser.error("--output-dir is required when --stage is set")

    try:
        raw_rows = _load_rows(args.input)
        for index, raw in enumerate(raw_rows):
            try:
                ReleaseRowV2.from_dict(raw)
            except (PatentReleaseSafetyError, PatentHFReleaseV2Error, ReleasePolicyError) as exc:
                raise SystemExit(
                    f"row[{index}] failed shape/policy checks: {exc}"
                ) from exc

        release = build_patent_hf_release_v2(
            raw_rows,
            organization=args.organization,
            version_tag=args.version_tag,
            dry_run=dry_run,
            output_dir=args.output_dir,
            max_rows_per_shard=args.max_rows_per_shard,
            source_root_cid=args.source_root_cid,
            index_root_cid=args.index_root_cid,
            evaluation_root_cid=args.evaluation_root_cid,
        )
        validation = validate_patent_hf_release_v2(release)
    except PatentReleaseSafetyError as exc:
        print(f"ERROR: rejected before staging: {exc}", file=sys.stderr)
        return 2
    except OrphanJoinError as exc:
        print(f"ERROR: orphan join rejected before staging: {exc}", file=sys.stderr)
        return 2
    except (PatentHFReleaseV2Error, ReleasePolicyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = {
        "artifact_count": validation["artifact_count"],
        "dry_run": release.dry_run,
        "evaluation_root_cid": release.evaluation_root_cid,
        "index_root_cid": release.index_root_cid,
        "layout_bundle_cid": release.layout_bundle_cid,
        "organization": release.organization,
        "policy_sha256": release.policy_sha256,
        "release_root_cid": release.release_root_cid,
        "source_root_cid": release.source_root_cid,
        "staged_root": release.staged_root,
        "total_row_count": validation["total_row_count"],
        "uses_hf_api_upload_file": False,
        "version_tag": release.version_tag,
    }
    print(json.dumps(summary, sort_keys=True, indent=2))
    if args.print_manifest:
        print(json.dumps(release.manifest_dict(), sort_keys=True, indent=2))
    if dry_run:
        print(
            "dry-run complete: no files staged and no remote upload attempted",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
