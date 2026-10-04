#!/usr/bin/env python3
"""Check local external-review submissions; emit a pending report when absent."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal.legal_review_admission import ReviewAdmissionError, intake_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--submission", action="append", default=[], type=Path)
    parser.add_argument("--context-artifact", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = intake_report(args.packet, submission_paths=args.submission, context_paths=args.context_artifact)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    except (ReviewAdmissionError, OSError) as error:
        parser.exit(1, f"review admission failed: {error}\n")
    print(json.dumps({"output": str(args.output.resolve()), "status": report["status"], "counts": report["counts"]}))
    return 1 if report["counts"]["rejected_structurally"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
