#!/usr/bin/env python3
"""Measure structural preservation and prepare separate richer human review."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs/autoencoders/alignment_structure_development_v1.json")
    parser.add_argument("--workspace-root", type=Path, default=REPOSITORY_ROOT.parent.parent)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(REPOSITORY_ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_structure_experiment import (
        run_structure_experiment,
    )

    try:
        report = run_structure_experiment(args.config, REPOSITORY_ROOT, args.workspace_root, args.output_directory)
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "qualified": False}), file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output_directory / "report.json"), "status": report["status"],
                      "parser_receipts_validated": report["parser_receipts_validated"],
                      "exact_preservation": {name: {key: assay[key] for key in ("rows", "exact_owner_restorations", "exact_named_counts")}
                          for name, assay in report["structural_summaries"].items()},
                      "new_review_items_pending": report["new_review_items_pending"], "completed_independent_reviews": 0,
                      "report_sha256": report["report_sha256"], "qualified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
