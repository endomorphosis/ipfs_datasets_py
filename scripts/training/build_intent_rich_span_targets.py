#!/usr/bin/env python3
"""Export replayable weak structured IntentIR targets from pinned SkillCenter spans."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--span-corpus-descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError("a fresh output directory is required")
    from ipfs_datasets_py.logic.intent_ir.formalize.rich_span_targets import export_skillcenter_rich_span_targets
    descriptor = export_skillcenter_rich_span_targets(
        json.loads(args.span_corpus_descriptor.read_bytes()), output=args.output)
    report = json.loads(Path(descriptor["path"]).read_bytes())
    print(json.dumps({"rich_targets": descriptor, "counts": report["counts"], "published": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
