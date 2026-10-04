#!/usr/bin/env python3
"""Prepare the aligned-retrieval study or measure its exposed B0/B1 baseline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=REPOSITORY_ROOT / "configs/autoencoders/alignment_study_development_v1.json")
    parser.add_argument("--expected-config-sha256")
    parser.add_argument("--workspace-root", type=Path, default=REPOSITORY_ROOT.parent.parent)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true",
                        help="Run deterministic compiler and cached-source retrieval on exposed development inputs.")
    args = parser.parse_args()
    if args.output_directory.exists() or args.output_directory.is_symlink():
        parser.error("output directory already exists; choose a fresh evidence directory")
    # Use this exact checkout and keep optional installer/model paths disabled.
    sys.path.insert(0, str(REPOSITORY_ROOT))
    os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")
    import ipfs_datasets_py

    if REPOSITORY_ROOT not in Path(ipfs_datasets_py.__file__).resolve().parents:
        parser.error("package import did not resolve to the canonical dataset checkout")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_study import (
        AlignmentStudyError,
        prepare_alignment_study,
        write_alignment_manifest,
    )
    try:
        report = prepare_alignment_study(
            args.config, REPOSITORY_ROOT, args.workspace_root, baseline=args.baseline,
            expected_config_sha256=args.expected_config_sha256,
        )
        destination = write_alignment_manifest(args.output_directory, report)
    except (AlignmentStudyError, ValueError, OSError) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc), "qualified": False}),
              file=sys.stderr)
        return 2
    print(json.dumps({"manifest": str(destination), "stage": report["stage"],
                      "manifest_sha256": report["manifest_sha256"], "qualified": False,
                      "primary_evaluation": report["primary_evaluation"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
