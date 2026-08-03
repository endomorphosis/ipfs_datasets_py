#!/usr/bin/env python3
"""Build deterministic, privacy-reviewed JusticeDAO patent/legal HF release artifacts.

Default mode is **dry-run**: the builder admits public rows, materializes a
content-addressed release in memory, and prints the plan.  No local staging
occurs unless ``--stage`` is supplied, and this script never performs a remote
Hub upload (no ``HfApi.upload_file`` path).

Input is a JSON array (or NDJSON) of release candidates.  Each candidate must
include record_id, artifact_kind, classification, payload, source_lineage, and
rights_review.  Private or mixed classification batches fail before staging.
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

from ipfs_datasets_py.processors.domains.patent.hf_release import (  # noqa: E402
    DEFAULT_DATASET_REPO_ID,
    PatentReleaseSafetyError,
    build_patent_hf_release,
    validate_patent_hf_release,
)
from ipfs_datasets_py.processors.domains.patent.release_policy import (  # noqa: E402
    ARTIFACT_KINDS,
    ReleaseCandidate,
    ReleasePolicyError,
)


def _load_candidates(path: Path) -> list[Mapping[str, Any]]:
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
        raise SystemExit("input must be a non-empty JSON array of candidates")
    rows = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping):
            raise SystemExit(f"candidate[{index}] must be an object")
        rows.append(item)
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build deterministic privacy-reviewed JusticeDAO patent/legal "
            "release artifacts (default: dry-run, no upload)."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to JSON array or NDJSON of release candidates",
    )
    parser.add_argument(
        "--dataset-id",
        default=DEFAULT_DATASET_REPO_ID,
        help=f"Target dataset id (default: {DEFAULT_DATASET_REPO_ID})",
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
        "--list-artifact-kinds",
        action="store_true",
        help="Print supported artifact kinds and exit",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.list_artifact_kinds:
        for kind in ARTIFACT_KINDS:
            print(kind)
        return 0

    # Explicit contract: this CLI has no upload path.
    if getattr(args, "upload", None) or getattr(args, "push", None):
        parser.error("remote upload is not supported by this builder")

    dry_run = not bool(args.stage)
    if not dry_run and args.output_dir is None:
        parser.error("--output-dir is required when --stage is set")

    try:
        candidates = _load_candidates(args.input)
        # Validate candidate shape early for clearer operator errors.
        for index, raw in enumerate(candidates):
            try:
                ReleaseCandidate.from_dict(raw)
            except ReleasePolicyError as exc:
                raise SystemExit(
                    f"candidate[{index}] failed policy shape checks: {exc}"
                ) from exc

        release = build_patent_hf_release(
            candidates,
            dataset_id=args.dataset_id,
            dry_run=dry_run,
            output_dir=args.output_dir,
            max_rows_per_shard=args.max_rows_per_shard,
        )
        validation = validate_patent_hf_release(release)
    except PatentReleaseSafetyError as exc:
        print(f"ERROR: rejected before staging: {exc}", file=sys.stderr)
        return 2
    except (ReleasePolicyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary = {
        "dataset_id": release.dataset_id,
        "dry_run": release.dry_run,
        "release_root_cid": release.release_root_cid,
        "artifact_count": validation["artifact_count"],
        "total_row_count": validation["total_row_count"],
        "policy_sha256": release.policy_sha256,
        "staged_root": release.staged_root,
        "uses_hf_api_upload_file": False,
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
