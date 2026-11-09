#!/usr/bin/env python3
"""Stage a pinned historical census migration; never open a DB or upload."""
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--source-pins", required=True, type=Path,
                        help="Reviewed JSON mapping of exact producer paths to SHA256")
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--migration-receipt", required=True, type=Path)
    parser.add_argument("--dataset-revision")
    parser.add_argument("--manifest-path-in-repo")
    parser.add_argument("--download-directory", type=Path)
    args = parser.parse_args(argv)
    os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS="1", IPFS_DATASETS_AUTO_INSTALL="0",
        IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI="0", IPFS_ACCEL_SKIP_CORE="1", TRANSFORMERS_OFFLINE="1")
    from ipfs_datasets_py.logic.autoformal.paired_span_migration import (
        fetch_historical_bundle, migrate_historical_paired_bundle)
    remote = (args.dataset_revision, args.manifest_path_in_repo, args.download_directory)
    if args.manifest is None:
        if any(value is None for value in remote):
            parser.error("local --manifest or all three bounded metadata-download arguments required")
        os.environ["HF_HUB_OFFLINE"] = "0"
        manifest = fetch_historical_bundle(revision=args.dataset_revision,
            manifest_path_in_repo=args.manifest_path_in_repo, directory=args.download_directory,
            expected_manifest_sha256=args.expected_manifest_sha256)
    else:
        if any(value is not None for value in remote):
            parser.error("local and remote input modes are mutually exclusive")
        manifest = args.manifest
    if args.migration_receipt.exists():
        parser.error("migration receipt already exists; preserve the prior attempt")
    result = migrate_historical_paired_bundle(manifest, args.output_directory,
        expected_manifest_sha256=args.expected_manifest_sha256,
        expected_sources=json.loads(args.source_pins.read_bytes()), receipt_path=args.receipt)
    with args.migration_receipt.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("new_manifest", "new_fingerprint",
        "paired_span_count", "historical_goal_count", "uploaded", "admitted")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
