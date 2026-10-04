#!/usr/bin/env python3
"""Compare opt-in qualifier parsing with source-pinned richer baseline evidence."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs/autoencoders/alignment_parser_development_v1.json")
    parser.add_argument("--workspace-root", type=Path, default=REPOSITORY_ROOT.parent.parent)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(REPOSITORY_ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_parser_experiment import (
        run_parser_experiment,
    )

    try:
        report = run_parser_experiment(args.config, REPOSITORY_ROOT, args.workspace_root, args.output_directory)
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "qualified": False}), file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output_directory / "report.json"), "status": report["status"],
                      "baseline_exact_replay_records": report["baseline_exact_replay_records"],
                      "development": report["summaries"]["development"], "exact_authored_gains": report["exact_authored_gains"],
                      "exact_authored_regressions": report["exact_authored_regressions"],
                      "report_sha256": report["report_sha256"], "qualified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
