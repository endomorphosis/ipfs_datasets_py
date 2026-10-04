#!/usr/bin/env python3
"""Record richer source/context review declarations and unresolved disagreements."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-bundle", type=Path, required=True)
    parser.add_argument("--expected-bundle-sha256", required=True)
    parser.add_argument("--submission", nargs=2, action="append", default=[], metavar=("PATH", "SHA256"))
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPOSITORY_ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.formalization.autoencoder import (
        alignment_richer_review_workflow as owner,
    )

    expected = REPOSITORY_ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/alignment_richer_review_workflow.py"
    if Path(owner.__file__).resolve() != expected:
        parser.error("richer review admission import comes from another checkout")
    try:
        report = owner.run_richer_review_admission(
            args.review_bundle, args.expected_bundle_sha256,
            [{"path": path, "sha256": sha} for path, sha in args.submission],
            args.output_directory, repository_root=REPOSITORY_ROOT,
        )
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "qualified": False}), file=sys.stderr)
        return 2
    print(json.dumps({
        "report": str(args.output_directory.absolute() / "report_private.json"),
        "status": report["status"], "submission_count": report["submission_count"],
        "status_counts": report["receipt"]["status_counts"],
        "completed_independent_reviews": 0, "qualified": False,
        "report_sha256": report["report_sha256"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
