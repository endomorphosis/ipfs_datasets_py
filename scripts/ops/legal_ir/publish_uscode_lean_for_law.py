#!/usr/bin/env python3
"""Assemble the sealed span cache and entity stitch into a Lean law package.

The package is justicedao/uscode-autoformal-lean-for-law. admitted and
formalized stay false. --upload and --lake are off unless passed. A build is
a compile receipt, not a legal admit. This script does not fetch Mathlib.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI", "0")

from ipfs_datasets_py.logic.autoformal.law_package import (  # noqa: E402
    LawPackageError,
    apply_lake_result,
    assemble_law_package,
    lake_build_law,
    upload_law_package,
    write_law_package,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="assemble a Lean package for the formalized Code")
    parser.add_argument("--stitch-dir", required=True)
    parser.add_argument("--spans", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--lake", action="store_true")
    args = parser.parse_args(argv)
    try:
        assembled = assemble_law_package(args.stitch_dir, args.spans)
        write_law_package(args.out, assembled)
        report = {
            "admitted": False,
            "formalized": False,
            "lake_error": "lake_not_run",
            "lake_ok": False,
            "modules": len(assembled["modules"]),
            "uploaded": False,
        }
        if args.lake:
            built = lake_build_law(args.out)
            apply_lake_result(args.out, built)
            report["lake_error"] = str(built.get("lake_error") or "")
            report["lake_ok"] = bool(built.get("lake_ok"))
            report["formalized"] = False
        if args.upload:
            published = upload_law_package(args.out)
            report["uploaded"] = bool(published.get("uploaded"))
            report["formalized"] = False
    except LawPackageError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
