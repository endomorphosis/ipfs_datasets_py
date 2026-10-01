#!/usr/bin/env python3
"""Diagnose the exact authored default Legal/UI blockers without running tools.

Writes a diagnostic report to a fresh local file. No Lake/SANY execution,
training, database/queue mutation, supervisor import, or network access occurs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Fresh local JSON file; existing files are never replaced")
    args = parser.parse_args(argv)
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("audit output must be a fresh path")
    from ipfs_datasets_py.logic.formalization.autoencoder.projection_context_audit import audit_default_projection_context
    report = audit_default_projection_context().to_dict()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"schema": report["schema"], "report_sha256": report["report_sha256"],
        "counts": report["counts"], "backend_executed": False, "qualified": False,
        "admitted": False, "supervisor_importable": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
