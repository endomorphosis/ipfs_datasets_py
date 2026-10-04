#!/usr/bin/env python3
"""Record source-only binding review declarations and unresolved disagreements."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviewer-packet", type=Path, required=True)
    parser.add_argument("--expected-packet-file-sha256", required=True)
    parser.add_argument("--submission", nargs=2, action="append", default=[], metavar=("PATH", "SHA256"))
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from ipfs_datasets_py.logic.legal_ir import canonical_binding_review_workflow as owner

    expected = REPOSITORY_ROOT / "ipfs_datasets_py/logic/legal_ir/canonical_binding_review_workflow.py"
    if Path(owner.__file__).resolve() != expected:
        parser.error("binding review recording import comes from another checkout")
    try:
        report = owner.run_binding_review_recording(
            args.reviewer_packet, args.expected_packet_file_sha256,
            [{"path": path, "sha256": sha} for path, sha in args.submission],
            args.output_directory, repository_root=REPOSITORY_ROOT,
        )
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps(dict(status="failed", reason=str(error), qualified=False)), file=sys.stderr)
        return 2
    print(json.dumps(dict(report=str(args.output_directory.absolute() / "report_private.json"),
                          status=report["status"], submission_count=report["submission_count"],
                          status_counts=report["status_counts"], completed_independent_reviews=0,
                          qualified=False, content_sha256=report["content_sha256"]), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
