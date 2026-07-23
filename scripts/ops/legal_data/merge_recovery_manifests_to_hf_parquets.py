from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_source_recovery_promotion import (
    merge_recovery_manifests_into_canonical_datasets,
)


def _read_manifest_paths(path_value: str) -> list[str]:
    path = Path(path_value).expanduser().resolve()
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch-merge legal recovery manifests into full canonical Hugging Face parquet files."
    )
    parser.add_argument("manifests", nargs="*", help="Recovery manifest JSON paths.")
    parser.add_argument("--manifest-list", help="Text file containing one recovery manifest path per line.")
    parser.add_argument("--output-dir", required=True, help="Directory for upload-ready merged parquet artifacts and report.")
    parser.add_argument("--hydrate-from-hf", action="store_true", help="Download current target parquets from Hugging Face before merging.")
    parser.add_argument("--publish-merged-to-hf", action="store_true", help="Upload full merged parquets back to their canonical HF paths.")
    parser.add_argument("--hf-token", help="Optional Hugging Face token override.")
    parser.add_argument("--hf-revision", help="Optional Hugging Face revision for hydration.")
    parser.add_argument("--hf-cache-dir", help="Optional Hugging Face cache directory.")
    parser.add_argument("--force-hf-download", action="store_true", help="Force re-download of hydrated HF parquet files.")
    parser.add_argument("--commit-message", help="Optional Hugging Face commit message for uploads.")
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    manifest_paths = list(args.manifests or [])
    if args.manifest_list:
        manifest_paths.extend(_read_manifest_paths(args.manifest_list))
    if not manifest_paths:
        parser.error("Provide at least one manifest path or --manifest-list.")
    if args.publish_merged_to_hf and not args.hydrate_from_hf:
        parser.error("--publish-merged-to-hf requires --hydrate-from-hf.")

    report = merge_recovery_manifests_into_canonical_datasets(
        manifest_paths,
        output_dir=args.output_dir,
        hydrate_from_hf=bool(args.hydrate_from_hf),
        hf_token=args.hf_token,
        hf_revision=args.hf_revision,
        hf_cache_dir=args.hf_cache_dir,
        force_hf_download=bool(args.force_hf_download),
        publish_merged_to_hf=bool(args.publish_merged_to_hf),
        hf_commit_message=args.commit_message,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Status: {report.get('status')}")
        print(f"Manifests: {report.get('manifest_count')} ({report.get('valid_manifest_count')} valid rows)")
        print(f"Targets: {report.get('target_count')} {report.get('status_counts')}")
        report_path = str(report.get("report_path") or "").strip()
        if report_path:
            print(f"Report: {report_path}")
        for target in list(report.get("targets") or [])[:10]:
            print(
                f"- {target.get('status')} {target.get('hf_dataset_id')} "
                f"{target.get('target_parquet_path')} rows={target.get('merged_row_count')} "
                f"local={target.get('target_local_parquet_path')}"
            )

    return 0 if str(report.get("status") or "") in {"success", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
