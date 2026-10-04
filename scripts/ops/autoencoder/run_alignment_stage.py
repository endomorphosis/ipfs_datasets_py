#!/usr/bin/env python3
"""Publish SHA-pinned inactive fit/score or raw source-ranking diagnostics."""
from __future__ import annotations

import argparse
import json
import sys
import types
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "rank", "score"))
    for name in ("declaration", "expected-bindings"):
        parser.add_argument("--" + name, required=True)
        parser.add_argument("--" + name + "-sha256", required=True)
        parser.add_argument("--" + name + "-bytes", required=True, type=int)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--lane-bundle-selections-json")
    parser.add_argument("--role-file-selections-json")
    for name in ("saved-rankings", "reference-bundle"):
        parser.add_argument("--" + name)
        parser.add_argument("--" + name + "-sha256")
        parser.add_argument("--" + name + "-bytes", type=int)
    parser.add_argument("--worker-timeout-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    for name, relative in (
        ("ipfs_datasets_py", "ipfs_datasets_py"),
        ("ipfs_datasets_py.logic", "ipfs_datasets_py/logic"),
        ("ipfs_datasets_py.logic.formalization", "ipfs_datasets_py/logic/formalization"),
        ("ipfs_datasets_py.logic.formalization.autoencoder", "ipfs_datasets_py/logic/formalization/autoencoder"),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(root / relative)]
        module.__package__ = name
        sys.modules[name] = module
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_stage_workflow import (
        _parse,
        run_alignment_stage,
    )

    def selection(name):
        path = getattr(args, name)
        sha = getattr(args, name + "_sha256")
        size = getattr(args, name + "_bytes")
        if path is None and sha is None and size is None:
            return None
        if path is None or sha is None or size is None:
            parser.error(name.replace("_", "-") + " requires path, SHA256 and bytes together")
        return {"path": path, "sha256": sha, "bytes": size}

    try:
        report = run_alignment_stage(args.stage, selection("declaration"), selection("expected_bindings"), args.output_directory,
            lane_bundle_selections=_parse(args.lane_bundle_selections_json.encode("utf-8")) if args.lane_bundle_selections_json else None,
            role_file_selections=_parse(args.role_file_selections_json.encode("utf-8")) if args.role_file_selections_json else None,
            saved_rankings_binding=selection("saved_rankings"), reference_bundle_binding=selection("reference_bundle"),
            worker_timeout_seconds=args.worker_timeout_seconds)
    except (ValueError, OSError):
        parser.error("selected diagnostic stage failed; no admission or numerical fit was performed")
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
