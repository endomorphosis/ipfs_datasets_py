#!/usr/bin/env python3
"""Inventory pinned SkillCenter sentence spans and export bounded weak IR pairs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-corpus-descriptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    from ipfs_datasets_py.logic.intent_ir.formalize.skillcenter_spans import export_skillcenter_span_corpus
    from ipfs_datasets_py.logic.intent_ir.formalize.span_training import build_skillcenter_span_pairs
    if args.output.exists():
        raise ValueError("a fresh output directory is required")
    descriptor = export_skillcenter_span_corpus(
        source_descriptor=json.loads(args.source_corpus_descriptor.read_bytes()), output=args.output)
    pairs = build_skillcenter_span_pairs(descriptor)
    (args.output / "descriptor.json").write_text(json.dumps(descriptor, indent=2, sort_keys=True) + "\n")
    (args.output / "paired-corpus.json").write_text(json.dumps(pairs, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"span_corpus": descriptor, "pair_counts": pairs["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
