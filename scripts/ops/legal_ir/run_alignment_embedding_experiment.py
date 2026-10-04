#!/usr/bin/env python3
"""Produce native source vectors and compare fixed richer retrieval controls."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs/autoencoders/alignment_embedding_development_v1.json")
    parser.add_argument("--workspace-root", type=Path, default=REPOSITORY_ROOT.parent.parent)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(REPOSITORY_ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_embedding_experiment import (
        run_embedding_experiment,
    )

    try:
        report = run_embedding_experiment(args.config, REPOSITORY_ROOT, args.workspace_root, args.output_directory)
    except (ValueError, OSError, ImportError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "qualified": False}), file=sys.stderr)
        return 2
    print(json.dumps({"report": str(args.output_directory / "report.json"), "status": report["status"],
                      "embedding_receipts_produced": report["embedding_receipts_produced"], "summaries": report["summaries"],
                      "report_sha256": report["report_sha256"], "qualified": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
