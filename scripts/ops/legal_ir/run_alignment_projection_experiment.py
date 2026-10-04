#!/usr/bin/env python3
"""Run the exposed synthetic projection experiment and prepare blinded review."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=REPOSITORY_ROOT/"configs/autoencoders/alignment_projection_development_v1.json")
    parser.add_argument("--workspace-root", type=Path, default=REPOSITORY_ROOT.parent.parent)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(REPOSITORY_ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_experiment import (
        run_projection_experiment,
    )

    try:
        report = run_projection_experiment(args.config, REPOSITORY_ROOT, args.workspace_root, args.output_directory)
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "qualified": False}), file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output_directory/"report.json"), "report_sha256": report["report_sha256"],
                      "status": report["status"], "completed_trials": sum(t["status"] == "completed" for t in report["trials"]),
                      "qualified": False, "primary_fidelity": report["primary_fidelity"]}, indent=2))
    return 0 if report["status"] == "completed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
