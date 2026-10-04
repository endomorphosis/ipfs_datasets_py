#!/usr/bin/env python3
"""Compare frozen source384 checkpoint endpoints with raw source retrieval."""
from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/autoencoders/alignment_checkpoint_development_v1.json")
    parser.add_argument("--workspace-root", type=Path, default=ROOT.parent.parent)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_checkpoint_experiment import (
        run_checkpoint_experiment,
    )

    try:
        with redirect_stdout(sys.stderr):
            report = run_checkpoint_experiment(args.config, ROOT, args.workspace_root, args.output_directory)
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "qualified": False}), file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output_directory / "report.json"), "status": report["status"],
        "representation_status": report["representation_status"], "checkpoint_inference_rows": report["checkpoint_inference_rows"],
        "retrieval_summaries": report["retrieval_summaries"], "report_sha256": report["report_sha256"], "qualified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
